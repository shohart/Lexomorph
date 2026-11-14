// Hand-authored: see build-info.h.
#include "build-info.h"
#include <string>

int llama_build_number(void)   { return 0; }
const char * llama_commit(void)       { return "ded522f8304554317e7ff8f88698dbbbca5425aa"; }
const char * llama_compiler(void)     { return "SuperDictateLLMHost"; }
const char * llama_build_target(void) { return "x86_64-apple-macosx"; }
const char * llama_build_info(void) {
    static std::string s = std::string("SuperDictateLLMHost-") + "ded522f8304554317e7ff8f88698dbbbca5425aa";
    return s.c_str();
}
