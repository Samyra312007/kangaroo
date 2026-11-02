#include <algorithm>
#include <utility>

#include "constants.hpp"
#include "rotating_log.hpp"
#include "stats/stats.hpp"

namespace flashCache {

RotatingLog::RotatingLog(uint64_t log_capacity, uint64_t block_size, SetsAbstract* sets,
    stats::LocalStatsCollector& log_stats, uint64_t readmit):
        _sets(sets),
        _log_stats(log_stats), 
        _total_capacity(log_capacity), 
        _total_size(0),
        _active_block(0),
        _num_partitions(KLOG_NUM_PARTITIONS),
        _readmit(readmit),
        _current_time(0) {
    _block_size = block_size;
    _log_stats["logCapacity"] = _total_capacity;
    _num_blocks = log_capacity / block_size;
    Block template_block = Block(block_size);
    _blocks.resize(_num_blocks, template_block);
    // allow last block to be smaller than the others
    if (log_capacity % block_size) {
        _num_blocks++;
        template_block._capacity = log_capacity % block_size;
        _blocks.push_back(template_block);
    }
}

void RotatingLog::_touchTime(const candidate_t& item) {
    if (item.request_time > _current_time) {
        _current_time = item.request_time;
    }
}

bool RotatingLog::_expired(const candidate_t& item) const {
    return item.expire_time != 0 && _current_time >= item.expire_time;
}

bool RotatingLog::_removeItemFromBlocks(const candidate_t& item) {
    for (auto& block : _blocks) {
        auto it = block._items.find(item);
        if (it != block._items.end()) {
            uint64_t size = it->obj_size;
            block._items.erase(it);
            block._size -= size;
            _total_size -= size;
            return true;
        }
    }
    return false;
}

void RotatingLog::_removeFromSetMatches(const candidate_t& item) {
    if (!_sets) {
        return;
    }
    for (auto& set_entry : _set_to_items) {
        auto it = std::find_if(set_entry.second.begin(), set_entry.second.end(),
                               [&](const candidate_t& x) { return x.id == item.id; });
        if (it != set_entry.second.end()) {
            set_entry.second.erase(it);
        }
    }
}

std::vector<candidate_t> RotatingLog::_dropExpired() {
    std::vector<candidate_t> removed;
    std::unordered_set<int64_t> seen;

    for (auto& block : _blocks) {
        std::vector<candidate_t> expired_items;
        for (const auto& item : block._items) {
            if (_expired(item) && seen.insert(item.id).second) {
                expired_items.push_back(item);
            }
        }

        for (const auto& item : expired_items) {
            _removeItemFromBlocks(item);
            _log_stats["expiredDrops"]++;
            _log_stats["expiredBytesDropped"] += item.obj_size;
            auto it = _item_active.find(item);
            if (it != _item_active.end()) {
                _item_active.erase(it);
            }
            _removeFromSetMatches(item);
            removed.push_back(item);
        }
    }

    auto active_it = _item_active.begin();
    while (active_it != _item_active.end()) {
        if (_expired(active_it->first) && seen.insert(active_it->first.id).second) {
            if (active_it->second) {
                _total_size -= active_it->first.obj_size;
            }
            _log_stats["expiredDrops"]++;
            _log_stats["expiredBytesDropped"] += active_it->first.obj_size;
            _removeFromSetMatches(active_it->first);
            active_it = _item_active.erase(active_it);
        } else {
            ++active_it;
        }
    }

    for (auto& set_entry : _set_to_items) {
        std::vector<candidate_t> filtered;
        for (const auto& item : set_entry.second) {
            if (_expired(item) && seen.insert(item.id).second) {
                _log_stats["expiredDrops"]++;
                _log_stats["expiredBytesDropped"] += item.obj_size;
            } else {
                filtered.push_back(item);
            }
        }
        set_entry.second = std::move(filtered);
    }

    return removed;
}

void RotatingLog::_dropExpiredBlock(Block& block) {
    std::vector<candidate_t> expired_items;
    std::unordered_set<int64_t> seen;

    for (const auto& item : block._items) {
        if (_expired(item) && seen.insert(item.id).second) {
            expired_items.push_back(item);
        }
    }

    for (const auto& item : expired_items) {
        auto block_it = block._items.find(item);
        if (block_it != block._items.end()) {
            uint64_t size = block_it->obj_size;
            block._items.erase(block_it);
            block._size -= size;
            _total_size -= size;
        }

        _log_stats["expiredDrops"]++;
        _log_stats["expiredBytesDropped"] += item.obj_size;
        auto active_it = _item_active.find(item);
        if (active_it != _item_active.end()) {
            _item_active.erase(active_it);
        }
        _removeFromSetMatches(item);
    }
}

void RotatingLog::_insert(candidate_t item) {
    _log_stats["bytes_written"] += item.obj_size;
    _total_size += item.obj_size;
    item.hit_count = 0;
    _blocks[_active_block].insert(item);
    _per_item_hits[item] = 0;
    if (_sets) {
        uint64_t set_num = *(_sets->findSetNums(item).begin());
        _set_to_items[set_num].push_back(item);
    }
    _item_active[item] = true;
    assert(_blocks[_active_block]._size <= _blocks[_active_block]._capacity);
}

std::vector<candidate_t> RotatingLog::_incrementBlockAndFlush() {
    std::vector<candidate_t> evicted;
    _active_block = (_active_block + 1) % _num_blocks;
    Block& current_block = _blocks[_active_block];

    _dropExpiredBlock(current_block);

    if (current_block._size) {
        evicted.reserve(current_block._items.size());
        for (const auto& item : current_block._items) {
            if (_item_active[item]) {
                // only move if not already in sets
                evicted.push_back(item);
            }
            // should always remove an item, otherwise code bug
            _item_active.erase(item);
        }
        _log_stats["numEvictions"] += current_block._items.size();
        _log_stats["sizeEvictions"] += current_block._size;
        _log_stats["numLogFlushes"]++;
        _total_size -= current_block._size;
        current_block._items.clear();
        current_block._size = 0;
    }
    return evicted;
}

std::vector<candidate_t> RotatingLog::_addSetMatches(std::vector<candidate_t> evicted) {
    if (_sets == nullptr) {
        return evicted;
    }
    std::vector<candidate_t> ret;
    for (auto item: evicted) {
        uint64_t set_num = *(_sets->findSetNums(item).begin());
        /* if already in set_indices, already moved over */
        if (_set_to_items[set_num].size()) {
            ret.reserve(ret.size() + _set_to_items[set_num].size());
            uint64_t size_moved = 0;
            std::vector<candidate_t> not_moved;
            for (auto item_evicted: _set_to_items[set_num]) {
                if (_expired(item_evicted)) {
                    _log_stats["expiredDrops"]++;
                    _log_stats["expiredBytesDropped"] += item_evicted.obj_size;
                    continue;
                }

                bool already_evicted = _item_active.find(item_evicted) == _item_active.end();
                if (!already_evicted && size_moved > EVICT_SET_LIMIT) {
                    not_moved.push_back(item_evicted);
                    continue;
                }
                item_evicted.hit_count = _per_item_hits[item_evicted];
                size_moved += item_evicted.obj_size;
                ret.push_back(item_evicted);
                if (!already_evicted) {
                    // do not update stats for items force evicted
                    _log_stats["num_early_evict"]++;
                    _log_stats["size_early_evict"] += item_evicted.obj_size;
                    _item_active[item_evicted] = false;
                }
            }
            _set_to_items[set_num] = not_moved;
        }
    }
    return ret;
}

std::vector<candidate_t> RotatingLog::insert(std::vector<candidate_t> items) {
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

        Block& current_block = _blocks[_active_block];
        _dropExpiredBlock(current_block);
        if (item.obj_size + current_block._size > current_block._capacity) {
            /* move active block pointer */
            std::vector<candidate_t> local_evict = _incrementBlockAndFlush();
            evicted.insert(evicted.end(), local_evict.begin(), local_evict.end());
            current_block = _blocks[_active_block];
        }
        _insert(item);
    }
    evicted = _addSetMatches(evicted);
    assert(_total_capacity >= _total_size);
    _log_stats["current_size"] = _total_size;
    return evicted;
}

void RotatingLog::insertFromSets(candidate_t item) {
    _touchTime(item);

    if (_expired(item)) {
        _log_stats["expiredSkippedStores"]++;
        _log_stats["expiredBytesSkipped"] += item.obj_size;
        return;
    }

    uint64_t set_num = *(_sets->findSetNums(item).begin());
    auto active_it = _item_active.find(item);
    if (active_it != _item_active.end()) {
        if (_expired(active_it->first)) {
            _total_size -= active_it->first.obj_size;
            _log_stats["expiredDrops"]++;
            _log_stats["expiredBytesDropped"] += active_it->first.obj_size;
            _item_active.erase(active_it);
        } else {
            _log_stats["num_early_evict"]--;
            _log_stats["size_early_evict"] -= item.obj_size;
            _item_active[item] = true;
            _set_to_items[set_num].push_back(item);
            return;
        }
    }

    Block& current_block = _blocks[_active_block];
    _dropExpiredBlock(current_block);
    if (item.obj_size + current_block._size > current_block._capacity) {
        _log_stats["bytes_rejected_from_sets"] += item.obj_size;
        _log_stats["num_rejected_from_sets"]++;
        return;
    }
    _log_stats["bytes_readmitted"] += item.obj_size;
    _log_stats["num_readmitted"]++;
    _log_stats["bytes_written"] += item.obj_size;
    _total_size += item.obj_size;
    current_block.insert(item);
    _item_active[item] = true;
    _set_to_items[set_num].push_back(item);
    _per_item_hits[item] = 0;
}

void RotatingLog::readmit(std::vector<candidate_t> items) {
    for (auto item: items) {
        _touchTime(item);

        if (_expired(item)) {
            _log_stats["expiredDrops"]++;
            _log_stats["expiredBytesDropped"] += item.obj_size;
            _per_item_hits.erase(item);
            continue;
        }

        uint64_t set_num = *(_sets->findSetNums(item).begin());
        auto active_it = _item_active.find(item);
        if (active_it != _item_active.end()) {
            if (_expired(active_it->first)) {
                if (active_it->second) {
                    _total_size -= active_it->first.obj_size;
                }
                _log_stats["expiredDrops"]++;
                _log_stats["expiredBytesDropped"] += active_it->first.obj_size;
                _item_active.erase(active_it);
                _removeFromSetMatches(active_it->first);
            } else {
                _log_stats["num_early_evict"]--;
                _log_stats["size_early_evict"] -= item.obj_size;
                _item_active[item] = true;
                _set_to_items[set_num].push_back(item);
            }
        } else if (_readmit && _per_item_hits[item] > _readmit) {
            _dropExpiredBlock(_blocks[_active_block]);
            if (_blocks[_active_block]._size + item.obj_size > _blocks[_active_block]._capacity) {
                /* don't want to clean another block, could be back in this mess */
                _log_stats["readmit_evicted"]++;
                _log_stats["readmit_evicted_size"] += item.obj_size;
                _per_item_hits.erase(item);
                continue;
            }
            _log_stats["bytes_readmitted"] += item.obj_size;
            _log_stats["num_readmitted"]++;
            _log_stats["bytes_written"] += item.obj_size;
            _set_to_items[set_num].push_back(item);
            _total_size += item.obj_size;
            _blocks[_active_block].insert(item);
            _per_item_hits[item] = 0;
            _item_active[item] = true;
        } 
        _per_item_hits.erase(item);
    }
    _log_stats["current_size"] = _total_size;
    assert(_total_capacity >= _total_size);
}

bool RotatingLog::find(candidate_t item) {
    _touchTime(item);
    auto it = _item_active.find(item);
    if (it == _item_active.end()) {
        _log_stats["misses"]++;
        return false;
    }

    const candidate_t stored = it->first;
    if (_expired(stored)) {
        if (it->second) {
            _total_size -= stored.obj_size;
        }
        _log_stats["expiredDrops"]++;
        _log_stats["expiredBytesDropped"] += stored.obj_size;
        _removeItemFromBlocks(stored);
        _removeFromSetMatches(stored);
        _item_active.erase(it);
        _log_stats["misses"]++;
        return false;
    }

    if (!(it->second)) {
        _log_stats["hits"]++;
        // pass along for hit tracking in sets
        bool found = _sets->trackHit(item);
        if (!found) {
            it->second = true;
        }
        return true;
    }

    _log_stats["hits"]++;
    _per_item_hits[item]++;
    return true;
}

double RotatingLog::ratioCapacityUsed() {
    return _total_size / _total_capacity;
}

std::vector<candidate_t> RotatingLog::enumerateSet(uint64_t set_num) {
    auto it = _set_to_items.find(set_num);
    if (it == _set_to_items.end()) {
        return {};
    }
    return it->second;
}

double RotatingLog::calcWriteAmp() {
    int64_t requested = _log_stats.get("stores_requested_bytes");
    if (requested <= 0) {
        return 0.0;
    }
    return _log_stats.get("bytes_written") / (double) requested;
}

void RotatingLog::flushStats() {
    _log_stats["bytes_written"] = 0;
    _log_stats["stores_requested"] = 0;
    _log_stats["stores_requested_bytes"] = 0;
    _log_stats["numEvictions"] = 0;
    _log_stats["sizeEvictions"] = 0;
    _log_stats["numLogFlushes"] = 0;
    _log_stats["misses"] = 0;
    _log_stats["hits"] = 0;
    _log_stats["num_early_evict"] = 0;
    _log_stats["size_early_evict"] = 0;
    _log_stats["bytes_rejected_from_sets"] = 0;
    _log_stats["num_rejected_from_sets"] = 0;
    _log_stats["expiredDrops"] = 0;
    _log_stats["expiredBytesDropped"] = 0;
    _log_stats["expiredSkippedStores"] = 0;
    _log_stats["expiredBytesSkipped"] = 0;
}

void RotatingLog::setCapacity(uint64_t capacity) {
    if (_total_capacity == capacity) {
        return;
    }
    _total_capacity = capacity;
    _log_stats["logCapacity"] = _total_capacity;
    if (_total_size > _total_capacity) {
        _dropExpired();
        if (_total_size > _total_capacity) {
            _log_stats["numEvictions"] += _total_size;
            _log_stats["sizeEvictions"] += _total_size;
            _log_stats["numLogFlushes"]++;
        }
        _item_active.clear();
        _set_to_items.clear();
        _blocks.clear();
        _total_size = 0;
        _active_block = 0;
    }
    _num_blocks = _block_size > 0 ? _total_capacity / _block_size : 0;
    Block template_block(_block_size);
    _blocks.resize(_num_blocks, template_block);
    if (_total_capacity % _block_size) {
        _num_blocks++;
        template_block._capacity = _total_capacity % _block_size;
        _blocks.push_back(template_block);
    }
    if (_active_block >= _num_blocks) {
        _active_block = 0;
    }
}

void RotatingLog::setNumPartitions(int partitions) {
    if (partitions < 1) {
        partitions = 1;
    }
    if (_num_partitions == partitions) {
        return;
    }
    _num_partitions = partitions;
    _block_size = (_total_capacity + (uint64_t)partitions - 1) / (uint64_t)partitions;
    if (_block_size < 1) {
        _block_size = 1;
    }
    _num_blocks = _total_capacity / _block_size;
    _blocks.clear();
    Block template_block(_block_size);
    _blocks.resize(_num_blocks, template_block);
    if (_total_capacity % _block_size) {
        _num_blocks++;
        template_block._capacity = _total_capacity % _block_size;
        _blocks.push_back(template_block);
    }
    if (_active_block >= _num_blocks) {
        _active_block = 0;
    }
    _item_active.clear();
    _set_to_items.clear();
    _total_size = 0;
    _log_stats["logPartitions"] = _num_partitions;
}

uint64_t RotatingLog::capacity() const {
    return _total_capacity;
}

uint64_t RotatingLog::currentSize() const {
    return _total_size;
}

int RotatingLog::numPartitions() const {
    return _num_partitions;
}

int64_t RotatingLog::bytesWritten() const {
    return _log_stats.get("bytes_written");
}

int64_t RotatingLog::storesRequestedBytes() const {
    return _log_stats.get("stores_requested_bytes");
}

} // namespace flashCache

