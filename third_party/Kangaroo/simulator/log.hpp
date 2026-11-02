#pragma once

#include <vector>
#include <list>
#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include "candidate.hpp"
#include "log_abstract.hpp"
#include "stats/stats.hpp"
#include "constants.hpp"

namespace flashCache {

// log, will evict everything together once it is full
class Log : public virtual LogAbstract {

    public:
        Log(uint64_t log_capacity, stats::LocalStatsCollector& log_stats, 
                uint64_t readmit);

        /* ----------- Basic functionality --------------- */

        /* insert multiple items (allows amortization of flash write), 
         * no guarantee for placement in multihash */
        std::vector<candidate_t> insert(std::vector<candidate_t> items);
        void insertFromSets(candidate_t item);
        
        /* returns true if the item is in sets layer */
        bool find(candidate_t item);
        
        /* ----------- Useful for Admission Policies --------------- */
        
        /* for readmission policies */
        void readmit(std::vector<candidate_t> items);

        /* returns ratio of total capacity used */
        double ratioCapacityUsed();
        
        /* returns every log object mapping to the given sets-layer set */
        std::vector<candidate_t> enumerateSet(uint64_t set_num);
        
        /* ----------- Other Bookeeping --------------- */

        double calcWriteAmp();
        void flushStats();

        void setCapacity(uint64_t capacity);
        void setNumPartitions(int partitions);
        uint64_t capacity() const;
        uint64_t currentSize() const;
        int numPartitions() const;
        int64_t bytesWritten() const;
        int64_t storesRequestedBytes() const;

    private:
        struct IndexEntry {
            candidate_t item;
            int64_t offset;
            int32_t tag;
            int64_t next;
            uint32_t valid;
            uint64_t eviction_meta;
        };

        static uint64_t _hash(int64_t id);
        int64_t _partitionOf(int64_t id) const;
        int32_t _bucketOf(int64_t id) const;
        int64_t _findIndex(int64_t id, int32_t& out_bucket) const;
        int64_t _findValidIndex(int64_t id, int32_t& out_bucket) const;
        int32_t _insertIndex(const candidate_t& item, int64_t offset);
        void _clearIndex();

        void _insert(candidate_t item);
        void _touchTime(const candidate_t& item);
        void _dropExpired();
        void _flushLog();
        bool _expired(const candidate_t& item) const;

        stats::LocalStatsCollector& _log_stats;
        std::vector<IndexEntry> _entries;
        std::vector<int32_t> _heads;
        int _num_partitions;
        std::unordered_map<candidate_t, uint64_t> _per_item_hits;
        uint64_t _total_capacity;
        uint64_t _total_size;
        uint64_t _readmit;
        int64_t _current_time;
};

} // namespace flashCache
