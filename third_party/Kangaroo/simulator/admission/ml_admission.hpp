#pragma once
#include <cmath>
#include <limits>
#include <unordered_map>
#include <vector>

#include "admission/admission.hpp"
#include "candidate.hpp"
#include "config.hpp"
#include "rand.hpp"
#include "stats/stats.hpp"

namespace admission {

/* Lightweight Phase 9 pre-flash admission policy.
 *
 * The production CacheLib track cannot run here without raw flash hardware,
 * so this policy reproduces the simulator side of paper section 5.5: compare
 * a probabilistic pre-flash admission policy with an ML-style feature scorer
 * that prefers objects likely to be useful on flash.
 */
class MLAdmission : public virtual Policy {
public:
    MLAdmission(const libconfig::Setting& settings,
               flashCache::SetsAbstract* sets,
               flashCache::LogAbstract* log,
               stats::LocalStatsCollector& admission_stats)
        : Policy(admission_stats, sets, log) {
        misc::ConfigReader cfg(settings);

        _target_ratio = cfg.read<float>("admitRatio", 0.9f);
        _oracle_scale = cfg.read<double>("oracleScale", 1000.0);
        _oracle_weight = cfg.read<double>("oracleWeight", 1.0);
        _size_penalty = cfg.read<double>("sizePenalty", 0.05);
        _bias = cfg.read<double>("bias", 2.0);
        _hot_cutoff = static_cast<uint64_t>(cfg.read<int>("hotCutoff", 1000));
        _rand_gen.seed(cfg.read<uint64_t>("rngSeed", 0xC0FFEEULL));
    }

    std::unordered_map<uint64_t, std::vector<candidate_t>> admit(
        std::vector<candidate_t> items) {
        std::unordered_map<uint64_t, std::vector<candidate_t>> ret = groupBasic(items);
        std::vector<candidate_t> evicted;

        for (auto& bin : ret) {
            trackPossibleAdmits(bin.second);
            for (auto it = bin.second.begin(); it != bin.second.end();) {
                if (should_admit(*it)) {
                    ++it;
                } else {
                    evicted.push_back(*it);
                    it = bin.second.erase(it);
                }
            }
            trackAdmitted(bin.second);
        }

        performReadmission(evicted);
        return ret;
    }

    std::vector<candidate_t> admit_simple(std::vector<candidate_t> items) {
        std::vector<candidate_t> admitted;
        admitted.reserve(items.size());

        trackPossibleAdmits(items);
        for (const auto& item : items) {
            if (should_admit(item)) {
                admitted.push_back(item);
            }
        }
        trackAdmitted(admitted);
        return admitted;
    }

private:
    double sigmoid(double x) const {
        return 1.0 / (1.0 + std::exp(-x));
    }

    double score(const candidate_t& item) const {
        double popularity = 0.0;

        if (item.oracle_count > 0) {
            popularity = static_cast<double>(item.oracle_count) / _oracle_scale;
        } else if (item.hit_count > 0) {
            popularity = static_cast<double>(item.hit_count);
        } else if (static_cast<uint64_t>(item.id) <= _hot_cutoff) {
            popularity = 1.0;
        }

        double size_penalty = _size_penalty *
            static_cast<double>(item.obj_size) / 4096.0;

        return _oracle_weight * popularity - size_penalty + _bias;
    }

    bool should_admit(const candidate_t& item) {
        double p = sigmoid(score(item));
        if (p > _target_ratio) {
            p = _target_ratio;
        }
        const uint64_t threshold =
            static_cast<uint64_t>(p * std::numeric_limits<uint64_t>::max());
        return _rand_gen.next() <= threshold;
    }

    float _target_ratio;
    double _oracle_scale;
    double _oracle_weight;
    double _size_penalty;
    double _bias;
    uint64_t _hot_cutoff;
    misc::Rand _rand_gen;
};

} // namespace admission
