ROUTER_BASE_URL   = http://localhost:20128
ROUTER_API_KEY    = dummy

MODEL_MANAGER           = ag/gemini-3-flash-agent     # manager/default codebase Q&A
MODEL_INTEGRITY         = ag/claude-sonnet-4-6        # data integrity + synthesis guard
MODEL_SCANNER           = ag/gemini-3-flash-agent     # code high/static assist
MODEL_ANALYZER          = ag/claude-sonnet-4-6        # phân tích requirements
MODEL_CODE_A            = ag/gemini-3-flash-agent     # code high
MODEL_CODE_B            = ag/claude-sonnet-4-6        # code deep
MODEL_REVIEWER          = ag/gemini-3-flash-agent     # review bugs
MODEL_TESTER            = ag/gemini-3-flash-agent     # viết tests
MODEL_SECURITY          = ag/claude-sonnet-4-6        # security audit
MODEL_DEBUGGER          = ag/gemini-3-flash-agent     # apply fixes
MODEL_WORKER            = ag/gemini-3.5-flash-extra-low # non-code/light tasks
MODEL_SYNTHESIZER       = ag/gemini-3-flash-agent     # merge output cuối
