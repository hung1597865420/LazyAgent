AZURE_OPENAI_ENDPOINT   = 
AZURE_OPENAI_API_KEY    = 
AZURE_API_VERSION       = 2025-01-01-preview

MODEL_MANAGER           = gpt-5.4-pro-3   # ask_codebase + pre-pass summarizer — true 1M context (2026-03-05)
MODEL_INTEGRITY         =                 # data integrity + synthesis guard (gpt-5.3-codex-4)
MODEL_SCANNER           =                 # static analysis: dead_code/perf_regression, temp=0.0 (gpt-5.3-codex-4)
MODEL_ANALYZER          =     # phân tích requirements
MODEL_CODE_A            =     # code chính
MODEL_CODE_B            =     # code phụ
MODEL_REVIEWER          =     # review bugs
MODEL_TESTER            =     # viết tests
MODEL_SECURITY          =     # security audit
MODEL_DEBUGGER          =     # apply fixes
MODEL_WORKER            =     # format, docs
MODEL_SYNTHESIZER       =     # merge output cuối
