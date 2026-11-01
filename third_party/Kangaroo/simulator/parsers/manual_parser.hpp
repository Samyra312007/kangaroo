#pragma once
#include <iostream>
#include <libconfig.h++>
#include <vector>

#include "../config.hpp"
#include "parser.hpp"

namespace parser {

/* Exact-request parser for integration / edge-case tests.
   Default trace.requests = ( id1, size1, id2, size2, ... );
   Phase 9 optional feature format:
     trace.requestStride = 3;  requests = ( id, size, oracle, id, size, oracle, ... );
     trace.requestStride = 4;  requests = ( id, size, oracle, expire, id, size, oracle, expire, ... ); */
class ManualParser : public virtual Parser {
public:
    ManualParser(const libconfig::Setting& settings) {
        try {
            if (settings.exists("trace") && settings["trace"].exists("requests")) {
                const libconfig::Setting& list = settings["trace"]["requests"];
                int n = list.getLength();

                int stride = 2;
                if (settings["trace"].exists("requestStride")) {
                    stride = settings["trace"]["requestStride"];
                }

                if (stride != 2 && stride != 3 && stride != 4) {
                    std::cerr << "ManualParser: trace.requestStride must be 2, 3, or 4\n";
                    stride = 2;
                }

                for (int i = 0; i + stride <= n; i += stride) {
                    Request req{};
                    req.id = static_cast<int64_t>(static_cast<int>(list[i]));
                    req.req_size = static_cast<int64_t>(static_cast<int>(list[i + 1]));
                    req.oracle_count = 0;
                    req.expire_time = 0;

                    if (stride >= 3) {
                        req.oracle_count = static_cast<int64_t>(
                            static_cast<int>(list[i + 2]));
                    }
                    if (stride >= 4) {
                        req.expire_time = static_cast<int64_t>(
                            static_cast<int>(list[i + 3]));
                    }

                    req.req_num = static_cast<int64_t>(i / stride);
                    req.time = static_cast<uint64_t>(req.req_num);
                    req.type = parser::GET;
                    requests.push_back(req);
                }
            }
        } catch (const libconfig::SettingException& ex) {
            std::cerr << "ManualParser exception at " << ex.getPath()
                      << ": " << ex.what() << std::endl;
        }
    }

    void go(VisitorFn visit) override {
        std::cout << "go: Generating " << requests.size() << " manual requests\n";
        for (const auto& req : requests) {
            visit(req);
        }
    }

private:
    std::vector<Request> requests;
};

} // namespace parser
