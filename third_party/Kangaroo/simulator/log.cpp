#include <iostream>
#include "log.hpp"
#include "stats/stats.hpp"

namespace flashCache {

Log::Log(uint64_t log_capacity, stats::LocalStatsCollector& log_stats, uint64_t readmit):
        _log_stats(log_stats), 
        _num_partitions(KLOG_NUM_PARTITIONS),
        _total_capacity(log_capacity), 
        _total_size(0),
        _readmit(readmit),
        _current_time(0) {
    _log_stats["logCapacity"] = _total_capacity;
    _log_stats["logPartitions"] = _num_partitions;
    _heads.assign((size_t)_num_partitions * (size_t)KLOG_INDEX_TABLE_SIZE, -1);
}

void Log::_touchTime(const candidate_t& item) {
    if (item.request_time > _current_time) {
        _current_time = item.request_time;
    }
}

bool Log::_expired(const candidate_t& item) const {
    return item.expire_time != 0 && _current_time >= item.expire_time;
}

void Log::_dropExpired() {
    int64_t expired_count = 0;
    int64_t expired_size = 0;

    for (auto& entry : _entries) {
        if (!entry.valid) {
            continue;
        }
        if (_expired(entry.item)) {
            entry.valid = 0;
            _total_size -= entry.item.obj_size;
            expired_count++;
            expired_size += entry.item.obj_size;
        }
    }

    if (expired_count > 0) {
        _log_stats["expiredDrops"] += expired_count;
        _log_stats["expiredBytesDropped"] += expired_size;
    }
}

void Log::_flushLog() {
    if (_entries.empty()) {
        return;
    }

    _dropExpired();

    int64_t evicted_count = 0;
    int64_t evicted_size = 0;
    for (const auto& entry : _entries) {
        if (entry.valid) {
            evicted_count++;
            evicted_size += entry.item.obj_size;
        }
    }

    if (evicted_count > 0) {
        _log_stats["numEvictions"] += evicted_count;
        _log_stats["sizeEvictions"] += evicted_size;
        _log_stats["numLogFlushes"]++;
    }

    _clearIndex();
    _total_size = 0;
    _per_item_hits.clear();
}

void Log::_insert(candidate_t item) {
    int32_t bucket = _bucketOf(item.id);
    int64_t idx = _findIndex(item.id, bucket);
    int64_t offset = _total_size;
    if (idx == -1) {
        idx = _insertIndex(item, offset);
    } else {
        _entries[idx].item = item;
        _entries[idx].valid = 1;
    }

    _log_stats["bytes_written"] += item.obj_size;
    _total_size += item.obj_size;
    item.hit_count = 0;
    if (_readmit) {
        _per_item_hits[item] = 0;
    }
    assert(_total_size <= _total_capacity);
}

std::vector<candidate_t> Log::insert(std::vector<candidate_t> items) {
    std::vector<candidate_t> evicted;
    for (auto item: items) {
        _touchTime(item);
        _log_stats["stores_requested"]++;
        _log_stats["stores_requested_bytes"] += item.obj_size;

        if (_expired(item)) {
            _log_stats["expiredSkippedStores"]++;
            _log_stats["expiredBytesSkipped"] += item.obj_size;
            continue;
        }

        _dropExpired();
        if (item.obj_size + _total_size > _total_capacity) {
            _flushLog();
        }
        _insert(item);
    }
    _log_stats["current_size"] = _total_size;
    assert(_total_capacity >= _total_size);
    return evicted;
}

void Log::insertFromSets(candidate_t item) {
    _touchTime(item);

    if (_expired(item)) {
        _log_stats["expiredSkippedStores"]++;
        _log_stats["expiredBytesSkipped"] += item.obj_size;
        return;
    }

    _dropExpired();
    if (item.obj_size + _total_size > _total_capacity) {
        _log_stats["bytes_rejected_from_sets"] += item.obj_size;
        _log_stats["num_rejected_from_sets"]++;
        return;
    }

    _log_stats["bytes_readmitted"] += item.obj_size;
    _log_stats["num_readmitted"]++;
    _log_stats["bytes_written"] += item.obj_size;
    int64_t offset = _total_size;
    _insertIndex(item, offset);
    _total_size += item.obj_size;
    assert(_total_size <= _total_capacity);
    _per_item_hits[item] = 0;
}

void Log::readmit(std::vector<candidate_t> items) {
    if (!_readmit) {
        return;
    }

    for (auto item: items) {
        _touchTime(item);

        if (_expired(item)) {
            _per_item_hits.erase(item);
            _log_stats["expiredDrops"]++;
            _log_stats["expiredBytesDropped"] += item.obj_size;
            continue;
        }

        _dropExpired();
        if (_per_item_hits[item] > _readmit && _total_size + item.obj_size < _total_capacity) {
            _log_stats["bytes_written"] += item.obj_size;
            _log_stats["bytes_readmitted"] += item.obj_size;
            _log_stats["num_readmitted"]++;
            _total_size += item.obj_size;
            _insertIndex(item, _total_size - item.obj_size);
            assert(_total_size <= _total_capacity);
            _per_item_hits[item] = 0;
        } else {
            _per_item_hits.erase(item);
        }
    }
    _log_stats["current_size"] = _total_size;
    assert(_total_capacity >= _total_size);
}

bool Log::find(candidate_t item) {
    _touchTime(item);
    int32_t bucket = _bucketOf(item.id);
    int64_t idx = _findValidIndex(item.id, bucket);
    if (idx == -1) {
        _log_stats["misses"]++;
        return false;
    }

    if (_expired(_entries[idx].item)) {
        _entries[idx].valid = 0;
        _total_size -= _entries[idx].item.obj_size;
        _log_stats["expiredDrops"]++;
        _log_stats["expiredBytesDropped"] += _entries[idx].item.obj_size;
        _log_stats["misses"]++;
        return false;
    }

    _log_stats["hits"]++;
    _entries[idx].item.hit_count++;
    if (_readmit) {
        _per_item_hits[item]++;
    }
    return true;
}

double Log::ratioCapacityUsed() {
    return _total_size / _total_capacity;
}

std::vector<candidate_t> Log::enumerateSet(uint64_t set_num) {
    (void)set_num;
    return {};
}

uint64_t Log::_hash(int64_t id) {
    uint64_t z = (uint64_t)id + 0x9e3779b97f4a7c15ULL;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

int64_t Log::_partitionOf(int64_t id) const {
    return (int64_t)(_hash(id) % (uint64_t)_num_partitions);
}

int32_t Log::_bucketOf(int64_t id) const {
    return (int32_t)((_hash(id) >> 6) % KLOG_INDEX_TABLE_SIZE);
}

int64_t Log::_findIndex(int64_t id, int32_t& out_bucket) const {
    int64_t partition = _partitionOf(id);
    int32_t bucket = _bucketOf(id);
    size_t slot = (size_t)((size_t)partition * (size_t)KLOG_INDEX_TABLE_SIZE + (size_t)bucket);
    int32_t head = _heads[slot];
    int32_t current = head;
    int guard = 0;
    while (current != -1) {
        if (_entries[current].item.id == id) {
            out_bucket = bucket;
            return current;
        }
        current = _entries[current].next;
        if (++guard > 10000) {
            break;
        }
    }
    return -1;
}

int64_t Log::_findValidIndex(int64_t id, int32_t& out_bucket) const {
    int64_t partition = _partitionOf(id);
    int32_t bucket = _bucketOf(id);
    size_t slot = (size_t)((size_t)partition * (size_t)KLOG_INDEX_TABLE_SIZE + (size_t)bucket);
    int32_t head = _heads[slot];
    int32_t current = head;
    int guard = 0;
    while (current != -1) {
        if (_entries[current].item.id == id && _entries[current].valid) {
            out_bucket = bucket;
            return current;
        }
        current = _entries[current].next;
        if (++guard > 10000) {
            break;
        }
    }
    return -1;
}

int32_t Log::_insertIndex(const candidate_t& item, int64_t offset) {
    int32_t bucket = _bucketOf(item.id);
    int64_t partition = _partitionOf(item.id);
    size_t slot = (size_t)((size_t)partition * (size_t)KLOG_INDEX_TABLE_SIZE + (size_t)bucket);
    int32_t head = _heads[slot];
    int32_t current = head;
    int guard = 0;
    while (current != -1) {
        if (_entries[current].item.id == item.id) {
            _entries[current].item = item;
            _entries[current].offset = offset;
            _entries[current].valid = 1;
            _entries[current].eviction_meta = 0;
            return current;
        }
        current = _entries[current].next;
        if (++guard > 10000) {
            break;
        }
    }

    int32_t index = (int32_t)_entries.size();
    IndexEntry entry;
    entry.item = item;
    entry.offset = offset;
    entry.tag = (int32_t)(_hash(item.id) & 0x7fffffff);
    entry.next = head;
    entry.valid = 1;
    entry.eviction_meta = 0;
    _entries.push_back(entry);
    _heads[slot] = index;
    return index;
}

void Log::_clearIndex() {
    _entries.clear();
    std::fill(_heads.begin(), _heads.end(), -1);
}

double Log::calcWriteAmp() {
    int64_t requested = _log_stats.get("stores_requested_bytes");
    if (requested <= 0) {
        return 0.0;
    }
    return _log_stats.get("bytes_written") / (double) requested;
}

void Log::flushStats() {
    _log_stats["bytes_written"] = 0;
    _log_stats["stores_requested"] = 0;
    _log_stats["stores_requested_bytes"] = 0;
    _log_stats["numEvictions"] = 0;
    _log_stats["sizeEvictions"] = 0;
    _log_stats["numLogFlushes"] = 0;
    _log_stats["misses"] = 0;
    _log_stats["hits"] = 0;
    _log_stats["expiredDrops"] = 0;
    _log_stats["expiredBytesDropped"] = 0;
    _log_stats["expiredSkippedStores"] = 0;
    _log_stats["expiredBytesSkipped"] = 0;
}

void Log::setCapacity(uint64_t capacity) {
    if (_total_capacity == capacity) {
        return;
    }
    _total_capacity = capacity;
    _log_stats["logCapacity"] = _total_capacity;

    if (_total_size > _total_capacity) {
        _dropExpired();

        if (_total_size > _total_capacity) {
            int64_t evicted_size = _total_size;
            _log_stats["numEvictions"] += _entries.size();
            _log_stats["sizeEvictions"] += evicted_size;
            _log_stats["numLogFlushes"]++;
            _clearIndex();
            _total_size = 0;
            _per_item_hits.clear();
        }
    }
}

void Log::setNumPartitions(int partitions) {
    if (partitions < 1) {
        partitions = 1;
    }
    if (_num_partitions == partitions) {
        return;
    }
    _num_partitions = partitions;
    _heads.assign((size_t)_num_partitions * (size_t)KLOG_INDEX_TABLE_SIZE, -1);
    for (size_t i = 0; i < _entries.size(); ++i) {
        if (_entries[i].valid) {
            int32_t bucket = _bucketOf(_entries[i].item.id);
            int64_t partition = _partitionOf(_entries[i].item.id);
            size_t slot = (size_t)((size_t)partition * (size_t)KLOG_INDEX_TABLE_SIZE + (size_t)bucket);
            _entries[i].next = _heads[slot];
            _heads[slot] = (int32_t) i;
        }
    }
    _log_stats["logPartitions"] = _num_partitions;
}

uint64_t Log::capacity() const {
    return _total_capacity;
}

uint64_t Log::currentSize() const {
    return _total_size;
}

int Log::numPartitions() const {
    return _num_partitions;
}

int64_t Log::bytesWritten() const {
    return _log_stats.get("bytes_written");
}

int64_t Log::storesRequestedBytes() const {
    return _log_stats.get("stores_requested_bytes");
}

}

