#pragma once
#include <iostream>
#include <libconfig.h++>
#include <vector>

#include "../config.hpp"
#include "parser.hpp"

namespace parser {

/* Exact-request parser for integration / edge-case tests.
   trace.requests = ( id1, size1, id2, size2, ... ); */
class ManualParser : public virtual Parser {
public:
    ManualParser(const libconfig::Setting& settings) {
        try {
            if (settings.exists("trace") && settings["trace"].exists("requests")) {
                const libconfig::Setting& list = settings["trace"]["requests"];
                int n = list.getLength();
                for (int i = 0; i + 1 < n; i += 2) {
                    Request req{};
                    req.id = static_cast<int64_t>(static_cast<int>(list[i]));
                    req.req_size = static_cast<int64_t>(static_cast<int>(list[i + 1]));
                    req.req_num = static_cast<int64_t>(i / 2);
                    req.time = static_cast<uint64_t>(i / 2);
                    req.type = parser::GET;
                    req.oracle_count = 0;
                    req.expire_time = 0;
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
