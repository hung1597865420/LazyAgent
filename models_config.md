ROUTER_BASE_URL   = http://localhost:20128
ROUTER_API_KEY    = dummy

MODEL_MANAGER           = cx/gpt-5.4-mini       # manager/default codebase Q&A tiết kiệm
MODEL_INTEGRITY         = cx/gpt-5.5-review     # data integrity + synthesis guard
MODEL_SCANNER           = cx/gpt-5.4-mini       # static assist/light scan
MODEL_ANALYZER          = cx/gpt-5.5-review     # phân tích requirements
MODEL_CODE_A            = cx/gpt-5.5            # code default
MODEL_CODE_B            = cx/gpt-5.5-review     # code alternative/review-leaning
MODEL_REVIEWER          = cx/gpt-5.5-review     # review bugs
MODEL_TESTER            = cx/gpt-5.5            # viết tests/adversarial
MODEL_SECURITY          = cx/gpt-5.5-review     # security audit
MODEL_DEBUGGER          = cx/gpt-5.5            # apply fixes
MODEL_WORKER            = cx/gpt-5.4-mini       # non-code/light tasks
MODEL_SYNTHESIZER       = cx/gpt-5.4-mini       # merge output cuối tiết kiệm

# 5.6 models are expensive; keep them as explicit/late fallback only:
# SPARE_MODELS=cx/gpt-5.4-mini,cx/gpt-5.5,cx/gpt-5.5-review,cx/gpt-5.6-sol,cx/gpt-5.6-sol-review
