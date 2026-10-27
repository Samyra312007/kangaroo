#include "log.hpp"
#include "stats/stats.hpp"

namespace flashCache {

Log::Log(uint64_t log_capacity, stats::LocalStatsCollector& log_stats, uint64_t readmit):
        _log_stats(log_stats), 
        _total_capacity(log_capacity), 
        _total_size(0),
        _readmit(readmit) {
    _log_stats["logCapacity"] = _total_capacity;
    _heads.assign((size_t)KLOG_NUM_PARTITIONS * (size_t)KLOG_INDEX_TABLE_SIZE, -1);
}

void Log::_insert(candidate_t item) {
    int32_t bucket = _bucketOf(item.id);
    int64_t idx = _findIndex(item.id, bucket);
    int64_t offset = _total_size;
    if (idx == -1) {
        idx = _insertIndex(item, offset);
    }
    _log_stats["bytes_written"] += item.obj_size;
    _log_stats["stores_requested"]++;
    _log_stats["stores_requested_bytes"] += item.obj_size;
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
        if (item.obj_size + _total_size > _total_capacity) {
            evicted.clear();
            for (auto& entry: _entries) {
                if (entry.valid) {
                    evicted.push_back(entry.item);
                }
            }
            _log_stats["numEvictions"] += evicted.size();
            _log_stats["sizeEvictions"] += _total_size;
            _log_stats["numLogFlushes"]++;
            _clearIndex();
            _total_size = 0;
        }
        _insert(item);
    }
    _log_stats["current_size"] = _total_size;
    assert(_total_capacity >= _total_size);
    return evicted;
}

void Log::insertFromSets(candidate_t item) {
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
    int32_t bucket = _bucketOf(item.id);
    int64_t idx = _findIndex(item.id, bucket);
    if (idx == -1) {
        _log_stats["misses"]++;
        return false;
    } else {
        _log_stats["hits"]++;
        _entries[idx].item.hit_count++;
        if (_readmit) {
            _per_item_hits[item]++;
        }
        return true;
    }
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
    return (int64_t)(_hash(id) % (uint64_t)KLOG_NUM_PARTITIONS);
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
    while (current != -1) {
        if (_entries[current].item.id == id) {
            out_bucket = bucket;
            return current;
        }
        current = _entries[current].next;
    }
    return -1;
}

int32_t Log::_insertIndex(const candidate_t& item, int64_t offset) {
    int32_t bucket = _bucketOf(item.id);
    int64_t partition = _partitionOf(item.id);
    size_t slot = (size_t)((size_t)partition * (size_t)KLOG_INDEX_TABLE_SIZE + (size_t)bucket);
    int32_t head = _heads[slot];
    int32_t previous = -1;
    int32_t current = head;
    while (current != -1) {
        if (_entries[current].item.id == item.id) {
            _entries[current].offset = offset;
            _entries[current].eviction_meta = 0;
            return current;
        }
        previous = current;
        current = _entries[current].next;
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
    if (previous == -1) {
        _heads[slot] = index;
    } else {
        _entries[previous].next = index;
    }
    return index;
}

void Log::_clearIndex() {
    _entries.clear();
    std::fill(_heads.begin(), _heads.end(), -1);
}

double Log::calcWriteAmp() {
    double ret = _log_stats["bytes_written"]/ (double) _log_stats["stores_requested_bytes"];
    return ret;
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
} 

}

