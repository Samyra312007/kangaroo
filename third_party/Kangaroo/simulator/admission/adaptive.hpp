#pragma once
#include <limits>
#include <deque>
#include <algorithm>

#include "admission/admission.hpp"
#include "rand.hpp"
#include "candidate.hpp"
#include "config.hpp"
#include "stats/stats.hpp"

namespace admission {

// AdaKanga: an online adaptive admission policy (Phase 10 extension).
// Wraps the random admission idea but continuously retunes its admit
// probability using a sliding window of recent possible/admitted bytes,
// with hysteresis to avoid oscillation.
class AdaptiveAdmission : public virtual Policy {
public:
    AdaptiveAdmission(const libconfig::Setting& settings, flashCache::SetsAbstract* sets,
        flashCache::LogAbstract* log, stats::LocalStatsCollector& admission_stats):
            Policy(admission_stats, sets, log) {
        misc::ConfigReader cfg(settings);
        _admit_ratio = cfg.read<float>("admitRatio", 0.9f);
        _target_ratio = cfg.read<float>("targetRatio", 0.9f);
        _min_ratio = cfg.read<float>("minRatio", 0.1f);
        _max_ratio = cfg.read<float>("maxRatio", 1.0f);
        _step = cfg.read<float>("step", 0.05f);
        _hysteresis = cfg.read<float>("hysteresis", 0.02f);
        _window = cfg.read<int>("window", 8);
        _admit_threshold = _admit_ratio * std::numeric_limits<uint64_t>::max();
        _rand_gen.seed(cfg.read<uint64_t>("rngSeed", 0xC0FFEEULL));
    }

    std::unordered_map<uint64_t, std::vector<candidate_t>> admit(std::vector<candidate_t> items) {
        std::unordered_map<uint64_t, std::vector<candidate_t>> ret = groupBasic(items);
        std::vector<candidate_t> evicted;
        uint64_t possible_bytes = 0, admitted_bytes = 0;
        for (auto& bin: ret) {
            trackPossibleAdmits(bin.second);
            for (auto it = bin.second.begin(); it != bin.second.end();) {
                possible_bytes += it->obj_size;
                if (_rand_gen.next() > _admit_threshold) {
                    evicted.push_back(*it);
                    it = bin.second.erase(it);
                } else {
                    admitted_bytes += it->obj_size;
                    ++it;
                }
            }
            trackAdmitted(bin.second);
        }
        _history.push_back({possible_bytes, admitted_bytes});
        if ((int)_history.size() > _window) _history.pop_front();
        adapt();
        performReadmission(evicted);
        return ret;
    }

    std::vector<candidate_t> admit_simple(std::vector<candidate_t> items) {
        std::vector<candidate_t> admitted;
        admitted.reserve(items.size());
        uint64_t possible_bytes = 0, admitted_bytes = 0;
        trackPossibleAdmits(items);
        for (auto it = items.begin(); it != items.end();) {
            possible_bytes += it->obj_size;
            if (_rand_gen.next() <= _admit_threshold) {
                admitted.push_back(*it);
                admitted_bytes += it->obj_size;
            }
            ++it;
        }
        _history.push_back({possible_bytes, admitted_bytes});
        if ((int)_history.size() > _window) _history.pop_front();
        trackAdmitted(admitted);
        adapt();
        return admitted;
    }

    float admitRatio() const { return _admit_ratio; }

private:
    struct Sample { uint64_t possible, admitted; };
    std::deque<Sample> _history;

    void adapt() {
        uint64_t p = 0, a = 0;
        for (auto& s : _history) { p += s.possible; a += s.admitted; }
        if (p == 0) return;
        float observed = (float)a / (float)p;
        float delta = observed - _target_ratio;
        if (std::fabs(delta) <= _hysteresis) return;
        if (delta < 0) _admit_ratio = std::min(_max_ratio, _admit_ratio + _step);
        else _admit_ratio = std::max(_min_ratio, _admit_ratio - _step);
        _admit_threshold = _admit_ratio * std::numeric_limits<uint64_t>::max();
    }

    float _admit_ratio, _target_ratio, _min_ratio, _max_ratio, _step, _hysteresis;
    int _window;
    uint64_t _admit_threshold;
    misc::Rand _rand_gen;
};

} // namespace admission
