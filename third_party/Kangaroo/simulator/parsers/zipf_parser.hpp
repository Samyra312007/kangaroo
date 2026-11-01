#pragma once
#include <iostream>
#include <fstream>
#include <string>
#include <stdint.h>
#include <cassert>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include "../constants.hpp"
#include "../lib/zipf.h"

typedef double double64_t;

namespace parser {

class ZipfParser : public virtual Parser {

public:
  ZipfParser(float alpha, uint64_t numObjects, uint64_t _numRequests,
             double objectScaling = 1.0)
    : zipf("", numObjects, alpha, 1), numRequests(_numRequests),
      _objectScaling(objectScaling) {
  }

  void go(VisitorFn visit) {
      std::cout << "go: Generating " 
         << numRequests << " requests\n";
    Request req;
    req.type = parser::GET;
    uint64_t obj_id;
    uint64_t obj_size;
    for (uint64_t i = 0; i < numRequests; i++){
      zipf.Sample(obj_id, obj_size);
      req.id = obj_id;
      /* Appendix B scaling: emulate larger/smaller objects while the
       * generator's object count (and therefore the Zipf shape) is
       * chosen by the config. */
      req.req_size = (int64_t)(obj_size * _objectScaling);
      if (req.req_size < 1) { req.req_size = 1; }
      req.req_num = i;
      visit(req);
    }
  }

private:
  ZipfRequests zipf;
  uint64_t numRequests;
  double _objectScaling;
};

} // namespace parser
