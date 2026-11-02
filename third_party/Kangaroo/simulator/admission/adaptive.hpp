#pragma once

#include <algorithm>
#include <cmath>
#include <limits>
#include <iostream>
#include <unordered_map>
#include <vector>

#include "admission/admission.hpp"
#include "candidate.hpp"
#include "config.hpp"
#include "constants.hpp"
#include "rand.hpp"
#include "stats/stats.hpp"

namespace admission {

class AdaptiveAdmission : public virtual Policy {
public:
    AdaptiveAdmission(const libconfig::Setting& settings, flashCache::SetsAbstract* sets,
        flashCache::LogAbstract* log, stats::LocalStatsCollector& admission_stats):
            Policy(admission_stats, sets, log) {
        misc::ConfigReader cfg(settings);

        _rand_gen.seed(cfg.read<uint64_t>("rngSeed", 0xC0FFEEULL));

        _admitRatio = cfg.read<double>("admitRatio", 0.90);
        _minRatio = cfg.read<double>("minRatio", 0.20);
        _maxRatio = cfg.read<double>("maxRatio", 1.00);
        _ratioStep = cfg.read<double>("ratioStep", 0.10);

        int setThreshold = cfg.read<int>("setThreshold", 2);
        int minThreshold = cfg.read<int>("minThreshold", 1);
        int maxThreshold = cfg.read<int>("maxThreshold", 6);
        _setThreshold = (uint64_t) clampInt(setThreshold, minThreshold, maxThreshold);
        _minThreshold = (uint64_t) minThreshold;
        _maxThreshold = (uint64_t) maxThreshold;

        _initialLogCapacity = _log ? _log->capacity() : 0;
        _maxLogFraction = cfg.read<double>("maxLogFraction", 1.0);
        _minLogFraction = cfg.read<double>("minLogFraction", 0.1);
        _currentLogFraction = cfg.read<double>("startLogFraction", 0.5);
        _logFractionStep = cfg.read<double>("logFractionStep", 0.1);

        _minPartitions = cfg.read<int>("minPartitions", 1);
        _maxPartitions = cfg.read<int>("maxPartitions", flashCache::KLOG_NUM_PARTITIONS);
        _currentPartitions = cfg.read<int>("partitions", 4);

        _minAdmitHits = (uint64_t) cfg.read<int>("minAdmitHits", 1);
        _maxMinAdmitHits = (uint64_t) cfg.read<int>("maxAdmitHits", 4);
        _minAdmitHits = clampU64(_minAdmitHits, 1, _maxMinAdmitHits);

        _shortTtl = (int64_t) cfg.read<int>("shortTtl", 0);
        _shortTtlEnabled = _shortTtl > 0;

        _intervalAccessesTarget = cfg.read<int>("interval", 2000);
        _writeCeilingBytes = (int64_t) cfg.read<int>("writeCeilingBytes", 400000);
        _missHysteresis = cfg.read<double>("missHysteresis", 0.01);
        _plateauIntervals = cfg.read<int>("plateauIntervals", 2);
        _printDecisions = cfg.read<int>("printDecisions", 1);

        _currentLogFraction = clamp(_currentLogFraction, _minLogFraction, _maxLogFraction);
        _admitRatio = clamp(_admitRatio, _minRatio, _maxRatio);
        _currentPartitions = clampInt(_currentPartitions, _minPartitions, _maxPartitions);

        _currentTime = 0;
        _shortTtlRejected = 0;
        _shortTtlRejectedBytes = 0;
        _expiredRejected = 0;
        _expiredRejectedBytes = 0;

        _intervalAccesses = 0;
        _intervalMisses = 0;
        _intervalAdmittedBytes = 0;
        _intervalLogBytesWritten = 0;
        _maxIntervalWriteBytes = 0;
        _lastLogBytesWritten = _log ? _log->bytesWritten() : 0;
        _bestMissRate = std::numeric_limits<double>::max();
        _lastMissRate = std::numeric_limits<double>::max();
        _lastWriteRate = 0.0;
        _plateau = 0;
        _initialised = false;

        applyLogCapacity();
        applyLogPartitions();

        _admitThreshold = (uint64_t)(std::llround(_admitRatio * (double) std::numeric_limits<uint64_t>::max()));
        recordFinalStats();
    }

    ~AdaptiveAdmission() override {
        if (_printDecisions) {
            std::cout << "AdaKanga final: admitRatio=" << _admitRatio
                      << " threshold=" << _setThreshold
                      << " minAdmitHits=" << _minAdmitHits
                      << " logFraction=" << _currentLogFraction
                      << " partitions=" << _currentPartitions
                      << " logBytes=" << _currentLogCapacity << "\n";
        }
    }

    std::unordered_map<uint64_t, std::vector<candidate_t>> admit(std::vector<candidate_t> items) {
        std::unordered_map<uint64_t, std::vector<candidate_t>> ret = groupBasic(items);
        std::vector<candidate_t> rejected;
        std::vector<candidate_t> rejectedForReadmission;
        updateClock(items);

        for (auto& bin : ret) {
            trackPossibleAdmits(bin.second);

            std::vector<candidate_t> admitted;
            for (auto item : bin.second) {
                if (isExpired(item)) {
                    _expiredRejected++;
                    _expiredRejectedBytes += item.obj_size;
                    _admission_stats["expiredRejected"]++;
                    _admission_stats["expiredRejectedBytes"] += item.obj_size;
                    continue;
                }

                if (isShortTtl(item)) {
                    _shortTtlRejected++;
                    _shortTtlRejectedBytes += item.obj_size;
                    _admission_stats["shortTtlRejected"]++;
                    _admission_stats["shortTtlRejectedBytes"] += item.obj_size;
                    continue;
                }

                uint64_t writePressure = std::max(_intervalAdmittedBytes, _intervalLogBytesWritten);
                if (writePressure + (uint64_t) item.obj_size > (uint64_t) _writeCeilingBytes) {
                    rejected.push_back(item);
                    rejectedForReadmission.push_back(item);
                    continue;
                }

                uint64_t random = _rand_gen.next();
                uint64_t accessCount = _accessCounts[item.id];
                bool thresholdOk = bin.second.size() >= _setThreshold;
                bool accessOk = accessCount >= _minAdmitHits;
                bool probabilityOk = _admitRatio >= 1.0 || random <= _admitThreshold;

                if (thresholdOk && accessOk && probabilityOk) {
                    admitted.push_back(item);
                    _intervalAdmittedBytes += (uint64_t) item.obj_size;
                } else {
                    rejected.push_back(item);
                    rejectedForReadmission.push_back(item);
                }
            }

            bin.second = admitted;
            trackAdmitted(bin.second);
        }

        performReadmission(rejectedForReadmission);
        return ret;
    }

    std::vector<candidate_t> admit_simple(std::vector<candidate_t> items) {
        std::vector<candidate_t> admitted;
        trackPossibleAdmits(items);
        updateClock(items);

        for (auto item : items) {
            if (isExpired(item)) {
                _expiredRejected++;
                _expiredRejectedBytes += item.obj_size;
                _admission_stats["expiredRejected"]++;
                _admission_stats["expiredRejectedBytes"] += item.obj_size;
                continue;
            }

            if (isShortTtl(item)) {
                _shortTtlRejected++;
                _shortTtlRejectedBytes += item.obj_size;
                _admission_stats["shortTtlRejected"]++;
                _admission_stats["shortTtlRejectedBytes"] += item.obj_size;
                continue;
            }

            uint64_t writePressure = std::max(_intervalAdmittedBytes, _intervalLogBytesWritten);
            if (writePressure + (uint64_t) item.obj_size > (uint64_t) _writeCeilingBytes) {
                continue;
            }

            uint64_t random = _rand_gen.next();
            uint64_t accessCount = _accessCounts[item.id];
            bool accessOk = accessCount >= _minAdmitHits;
            bool probabilityOk = _admitRatio >= 1.0 || random <= _admitThreshold;

            if (accessOk && probabilityOk) {
                admitted.push_back(item);
                _intervalAdmittedBytes += (uint64_t) item.obj_size;
            }
        }

        trackAdmitted(admitted);
        return admitted;
    }

    void noteAccess(candidate_t item, bool hit) override {
        _currentTime = std::max(_currentTime, item.request_time);
        _accessCounts[item.id]++;
        _intervalAccesses++;
        if (!hit) {
            _intervalMisses++;
        }
        if (_log) {
            int64_t currentLogBytesWritten = _log->bytesWritten();
            if (currentLogBytesWritten > _lastLogBytesWritten) {
                _intervalLogBytesWritten += (uint64_t) (currentLogBytesWritten - _lastLogBytesWritten);
            }
            _lastLogBytesWritten = currentLogBytesWritten;
        }
        if (_intervalAccessesTarget > 0 && _intervalAccesses >= _intervalAccessesTarget) {
            runController();
        }
    }

    double admitRatio() const { return _admitRatio; }
    uint64_t threshold() const { return _setThreshold; }
    int partitions() const { return _currentPartitions; }
    uint64_t logCapacity() const { return _currentLogCapacity; }

private:
    void updateClock(const std::vector<candidate_t>& items) {
        for (const auto& item : items) {
            _currentTime = std::max(_currentTime, item.request_time);
        }
    }

    bool isExpired(const candidate_t& item) const {
        return item.expire_time != 0 && _currentTime >= item.expire_time;
    }

    bool isShortTtl(const candidate_t& item) const {
        if (!_shortTtlEnabled || item.expire_time == 0) {
            return false;
        }
        int64_t now = std::max(_currentTime, item.request_time);
        int64_t remaining = item.expire_time - now;
        return remaining <= _shortTtl;
    }

    uint64_t clampU64(uint64_t value, uint64_t low, uint64_t high) const {
        return std::max(low, std::min(high, value));
    }

    int clampInt(int value, int low, int high) const {
        return std::max(low, std::min(high, value));
    }

    double clamp(double value, double low, double high) const {
        return std::max(low, std::min(high, value));
    }

    uint64_t targetLogCapacity() const {
        uint64_t target = (uint64_t)(std::llround((double) _initialLogCapacity * _currentLogFraction));
        if (target < 1) {
            target = 1;
        }
        return target;
    }

    void applyLogCapacity() {
        _currentLogCapacity = targetLogCapacity();
        if (_log) {
            _log->setCapacity(_currentLogCapacity);
        }
    }

    void applyLogPartitions() {
        if (_log) {
            _log->setNumPartitions(_currentPartitions);
        }
    }

    void recordFinalStats() {
        _admission_stats["admitRatioPermille"] = (int64_t) (_admitRatio * 1000.0);
        _admission_stats["setThreshold"] = (int64_t) _setThreshold;
        _admission_stats["minAdmitHits"] = (int64_t) _minAdmitHits;
        _admission_stats["logFractionPermille"] = (int64_t) (_currentLogFraction * 1000.0);
        _admission_stats["partitions"] = (int64_t) _currentPartitions;
        _admission_stats["logCapacityBytes"] = (int64_t) _currentLogCapacity;
        _admission_stats["writeCeilingBytes"] = _writeCeilingBytes;
        _admission_stats["shortTtl"] = _shortTtl;
        _admission_stats["shortTtlRejected"] = _shortTtlRejected;
        _admission_stats["shortTtlRejectedBytes"] = _shortTtlRejectedBytes;
        _admission_stats["expiredRejected"] = _expiredRejected;
        _admission_stats["expiredRejectedBytes"] = _expiredRejectedBytes;
        _admission_stats["intervalAdmittedBytes"] = (int64_t) _intervalAdmittedBytes;
        _admission_stats["intervalLogBytesWritten"] = (int64_t) _intervalLogBytesWritten;
        _admission_stats["maxIntervalWriteBytes"] = (int64_t) _maxIntervalWriteBytes;
    }

    void logDecision(const std::string& reason) {
        _admission_stats["controllerDecisions"]++;
        if (_printDecisions) {
            uint64_t writeBytes = std::max(_intervalAdmittedBytes, _intervalLogBytesWritten);
            std::cout << "AdaKanga decision " << reason << ": admitRatio=" << _admitRatio
                      << " threshold=" << _setThreshold
                      << " minAdmitHits=" << _minAdmitHits
                      << " logFraction=" << _currentLogFraction
                      << " partitions=" << _currentPartitions
                      << " logBytes=" << _currentLogCapacity
                      << " intervalWriteBytes=" << writeBytes
                      << " ceilingBytes=" << _writeCeilingBytes << "\n";
        }
        recordFinalStats();
    }

    void tighten() {
        bool changed = false;

        if (_minAdmitHits < _maxMinAdmitHits) {
            _minAdmitHits++;
            changed = true;
        } else if (_admitRatio > _minRatio + 1e-9) {
            _admitRatio = std::max(_minRatio, _admitRatio - _ratioStep);
            _admitThreshold = (uint64_t)(std::llround(_admitRatio * (double) std::numeric_limits<uint64_t>::max()));
            changed = true;
        } else if (_setThreshold < _maxThreshold) {
            _setThreshold++;
            changed = true;
        } else if (_currentLogFraction > _minLogFraction + 1e-9) {
            _currentLogFraction = std::max(_minLogFraction, _currentLogFraction - _logFractionStep);
            applyLogCapacity();
            changed = true;
        } else if (_currentPartitions > _minPartitions) {
            _currentPartitions = std::max(_minPartitions, _currentPartitions / 2);
            applyLogPartitions();
            changed = true;
        }

        if (changed) {
            logDecision("tighten");
        }
    }

    void improve() {
        bool changed = false;

        if (_minAdmitHits > 1) {
            _minAdmitHits--;
            changed = true;
        } else if (_currentLogFraction < _maxLogFraction - 1e-9) {
            _currentLogFraction = std::min(_maxLogFraction, _currentLogFraction + _logFractionStep);
            applyLogCapacity();
            changed = true;
        } else if (_admitRatio < _maxRatio - 1e-9) {
            _admitRatio = std::min(_maxRatio, _admitRatio + _ratioStep);
            _admitThreshold = (uint64_t)(std::llround(_admitRatio * (double) std::numeric_limits<uint64_t>::max()));
            changed = true;
        } else if (_setThreshold > _minThreshold) {
            _setThreshold--;
            changed = true;
        } else if (_currentPartitions < _maxPartitions) {
            _currentPartitions = std::min(_maxPartitions, _currentPartitions + 4);
            applyLogPartitions();
            changed = true;
        }

        if (changed) {
            logDecision("improve");
        }
    }

    void improveCapacity() {
        bool changed = false;

        if (_currentLogFraction < _maxLogFraction - 1e-9) {
            _currentLogFraction = std::min(_maxLogFraction, _currentLogFraction + _logFractionStep);
            applyLogCapacity();
            changed = true;
        } else if (_currentPartitions < _maxPartitions) {
            _currentPartitions = std::min(_maxPartitions, _currentPartitions + 4);
            applyLogPartitions();
            changed = true;
        }

        if (changed) {
            logDecision("increaseCapacity");
        }
    }

    void runController() {
        double missRate = _intervalAccesses > 0 ? (double) _intervalMisses / (double) _intervalAccesses : 0.0;
        uint64_t writeBytes = std::max(_intervalAdmittedBytes, _intervalLogBytesWritten);
        double writeRate = _intervalAccesses > 0 ? (double) writeBytes / (double) _intervalAccesses : 0.0;
        double safeWriteRate = _intervalAccessesTarget > 0 ? (double) _writeCeilingBytes / (double) _intervalAccessesTarget : 0.0;
        bool safe = writeBytes <= (uint64_t) _writeCeilingBytes;
        _maxIntervalWriteBytes = std::max(_maxIntervalWriteBytes, writeBytes);

        if (!safe) {
            tighten();
            _plateau = 0;
        } else if (!_initialised) {
            _bestMissRate = missRate;
            _initialised = true;
        } else if (missRate < _bestMissRate - _missHysteresis) {
            _bestMissRate = missRate;
            _plateau = 0;
        } else {
            _plateau++;
            if (plateauIntervalsReached()) {
                if (writeRate > safeWriteRate * 0.9) {
                    tighten();
                } else if (missRate <= _bestMissRate + _missHysteresis) {
                    improveCapacity();
                }
                _plateau = 0;
            }
        }

        _admission_stats["lastIntervalMissRate"] = (int64_t) (missRate * 10000.0);
        _admission_stats["lastIntervalAdmittedBytes"] = (int64_t) _intervalAdmittedBytes;
        _admission_stats["lastIntervalLogBytesWritten"] = (int64_t) _intervalLogBytesWritten;
        _admission_stats["lastIntervalWriteRateBytes"] = (int64_t) writeRate;
        _admission_stats["bestIntervalMissRate"] = (int64_t) (_bestMissRate * 10000.0);
        _admission_stats["controllerIntervals"]++;

        _intervalAccesses = 0;
        _intervalMisses = 0;
        _intervalAdmittedBytes = 0;
        _intervalLogBytesWritten = 0;
    }

    bool plateauIntervalsReached() const {
        return _plateauIntervals > 0 && _plateau >= _plateauIntervals;
    }

    double _admitRatio;
    double _minRatio;
    double _maxRatio;
    double _ratioStep;

    uint64_t _minAdmitHits;
    uint64_t _maxMinAdmitHits;

    uint64_t _setThreshold;
    uint64_t _minThreshold;
    uint64_t _maxThreshold;
    uint64_t _admitThreshold;

    uint64_t _initialLogCapacity;
    uint64_t _currentLogCapacity;
    double _maxLogFraction;
    double _minLogFraction;
    double _currentLogFraction;
    double _logFractionStep;

    int _minPartitions;
    int _maxPartitions;
    int _currentPartitions;

    int64_t _shortTtl;
    bool _shortTtlEnabled;
    int64_t _currentTime;
    int64_t _shortTtlRejected;
    int64_t _shortTtlRejectedBytes;
    int64_t _expiredRejected;
    int64_t _expiredRejectedBytes;

    int _intervalAccessesTarget;
    int64_t _writeCeilingBytes;
    double _missHysteresis;
    int _plateauIntervals;
    int _printDecisions;

    int _intervalAccesses;
    int _intervalMisses;
    uint64_t _intervalAdmittedBytes;
    uint64_t _intervalLogBytesWritten;
    uint64_t _maxIntervalWriteBytes;
    int64_t _lastLogBytesWritten;

    double _bestMissRate;
    double _lastMissRate;
    double _lastWriteRate;
    int _plateau;
    bool _initialised;

    std::unordered_map<uint64_t, uint32_t> _accessCounts;

    misc::Rand _rand_gen;
};

} // namespace admission
