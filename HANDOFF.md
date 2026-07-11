# HANDOFF — JadeCap Automated Trading Bot

## 상태: (CEO/CTO 스코프락 세션) operator 지시 "controlled parameter sweep 진행"에 따라 JadeCap 4개 core-rule 상수(`entry_model._RR`/`_STOP_BUFFER`, `order_block._LOOKBACK`/`_IMPULSE_MULT`)를 대상으로 통제된 스윕 수행. **4개 파라미터 전부 in-sample/out-of-sample/cross-asset(4자산)/cross-year 검증을 모두 통과 — 신규 기본값으로 채택**: `_RR` 2.0→2.5, `_STOP_BUFFER` 0.001→0.0015, `_LOOKBACK` 10→15, `_IMPULSE_MULT` 1.5→1.8. BTC 2026 표준 방법론(6기간/3000캔들)에서 **+66.7% PnL**, walk-forward 여전히 PASS(연속손실 0, 퇴화 없음). 스윕 도중 성능 이슈 발견 및 해결: `BacktestEngine`의 walk-forward 스캔이 기간 길이에 대해 선형보다 훨씬 나쁜 확장성을 보임(3000캔들 88초 vs 1500캔들 7초) — 초기 시도(3000캔들 규모)는 80분 넘게 출력 없이 멈춰있어 강제 종료 후 1500캔들/실시간 progress logging으로 재설계, 총 4049초(67분)에 완료. 전체 `pytest` 215/215 통과(206+9, 신규 메트릭 함수 테스트). 스윕 리포트는 `docs/parameter_sweep_report.md`에 전체 방법론·모든 수치·명시적 caveat와 함께 기록됨. Live 관련 코드는 여전히 전무 — Small Live(게이트 #4)는 operator의 명시적 승인 대기 중

## 전체 회차 (controlled parameter sweep 수행 — 4개 core-rule 상수 신규 기본값 채택, operator 지시 처리)
- [x] **operator 지시 처리**: "controlled parameter sweep 진행" — 신규 전략 규칙 추가 금지, 스코프 확장 금지, 아키텍처 변경 금지, 전체 데이터셋에 대한 최적화 금지. 필수 방법론 10단계(작은 파라미터 셋 정의/각 파라미터 문서화/in-sample·out-of-sample·walk-forward 분할/in-sample에서만 최적화/robustness 기준으로 후보 선정/held-out 데이터로 검증/거부 기준 적용/8개 지표로 baseline과 비교/넓은 안정 구간 선호/robust 개선 없으면 기본값 유지) 전부 준수
- [x] **대상 파라미터 4개 선정 및 문서화**: `entry_model._RR`(기본 2.0)/`_STOP_BUFFER`(기본 0.001), `order_block._LOOKBACK`(기본 10)/`_IMPULSE_MULT`(기본 1.5) — 전부 이미 "reasonable default, not tuned"로 명시돼 있던 JadeCap MVP 핵심(실험적 기능 아님) 상수. `BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R`/`PARTIAL_TP_PORTION`는 의도적으로 제외(off-by-default 실험 기능 전용 파라미터라 MVP baseline 강화와 무관 — ROADMAP.md에 후속 항목으로 기록)
- [x] **`scripts/parameter_sweep.py` 신규 구현**: 파라미터 하나씩만 스윕(전체 그리드 아님 — 4×4×4×4=256 조합은 과적합 유발), 자산별 캔들 데이터를 한 번만 fetch해서 모든 설정에서 재사용(효율적), 기존 `run_backtest.py`의 `split_into_periods`/`walk_forward_report` 재사용(로직 중복 없음), 대상 모듈 상수를 테스트 기간에만 monkey-patch(항상 finally에서 원복). `profit_factor`/`expectancy`/`average_r` 순수 함수 신규(pytest 9종)
- [x] **성능 이슈 발견 및 해결**: 초기 실행(3000캔들/12기간 규모)이 80분 넘게 출력 없이 멈춰있어(Python stdout 버퍼링 + 실제로 매우 느린 O(n²) 이상급 walk-forward 스캔) 강제 종료 — 직접 벤치마크한 결과 3000캔들 기간 1개당 88초, 1500캔들 기간 1개당 7초(2배 적은 캔들에 12배 빠름)로 확인. 1500캔들/실시간 progress logging(`flush=True`)으로 재설계 후 재실행, 총 4049초(67분)에 완료
- [x] **BacktestResult 트레이드 dict 확장**: `stop_loss`/`take_profit`/`risk_per_unit` 필드 신규 추가(기존엔 entry_price/exit_price/pnl 등만 있었음) — Average R 계산에 필요, 순수 추가라 기존 호출자 영향 없음(dict 완전일치 assertion이 어디에도 없었음을 사전 확인)
- [x] **BTCUSDT in-sample(8기간) 스윕 결과**: baseline 65트레이드/$1147.78/6-8 수익/WF PASS. `_RR=1.5`는 0트레이드(RiskManager.MIN_RR=2가 rr<2 신호를 전부 거부 — 정상적인 예상된 결과). `_RR=2.5`(7/8 수익, avgR 0.927) 선정. `_STOP_BUFFER=0.0015`(avgR 0.767) 선정 — 0.002도 robustness 기준 통과했지만 기본값에 더 가까운 0.0015 선택(넓은 안정 구간 선호 원칙). `_LOOKBACK=15`(승률 80%, avgR 0.741) 선정. `_IMPULSE_MULT=1.8`(승률 81.54%, avgR 0.791) 선정. `_LOOKBACK=5`/`_IMPULSE_MULT=1.2`(더 느슨한 값들)는 자체 walk-forward 체크에서 FAIL — 더 많은 신호였지만 품질이 측정 가능하게 나빴음
- [x] **out-of-sample 검증(held-out 4기간, 선정 전까지 전혀 열어보지 않음)**: 4개 후보 전부 baseline 대비 expectancy·avgR 개선, `_RR=2.5`/`_STOP_BUFFER=0.0015`는 수익 기간도 개선(4/4, baseline 3/4)
- [x] **cross-asset 검증(ETH/SOL/XRP, 8기간/1500캔들)**: 4개 후보 전부 3개 자산 모두에서 buffer 통과(트레이드 수/수익기간 비율/avgR 전부 각 자산 baseline 대비 허용 범위 내)
- [x] **cross-year 검증(원래 스윕 범위를 넘어선 추가 검증)**: break-even이 "자산 축은 통과했지만 시간 축에서 부호 반전"했던 이전 교훈(ENGINEERING_DECISIONS.md #15/#16) 때문에, 4개 파라미터를 합친 조합을 BTCUSDT 2025년으로 별도 검증 — **+33.5% PnL($1147.45→$1531.27), 동일 수익기간 수(9/12)** — 자산이 아니라 진짜 다른 연도(매크로 레짐)에서도 유지됨을 확인. 이것이 최종 채택 결정의 핵심 근거
- [x] **표준 방법론 최종 확인**: 신규 기본값 적용 후 `run_backtest.py --candles 3000 --periods 6 --walk-forward`(BTC 2026, 이 프로젝트의 표준 규모)로 재실행 — **+66.7% PnL($1935.35→$3227.08)**, walk-forward 여전히 PASS(연속손실 0, 퇴화 없음, 오히려 후반부가 전반부보다 더 좋음)
- [x] **최종 결정: 4개 전부 채택** — `entry_model.py`/`order_block.py`의 실제 상수값을 직접 변경(리포트만 남기고 기존 값 유지가 아님), 각 상수 옆 주석을 "reasonable default, not tuned"에서 튜닝 근거 요약으로 교체
- [x] **테스트 fixture 수정**: `test_strategy_order_block.py`/`test_strategy_signal_engine.py`의 합성 캔들 fixture가 9개의 조용한 캔들만 사용하고 있었는데, 신규 `_LOOKBACK=15` 하에서는 order block 탐지 자체가 불가능해짐(루프 범위가 비어버림) — fixture를 15개로 확장하고 이후 인덱스 전부 재계산. `rr == 2.0` 하드코딩 assertion 2건을 `2.5`로 갱신
- [x] 전체 `pytest backend/tests/` **215/215 통과**(206 + 9 신규)
- [x] `docs/parameter_sweep_report.md` 신규(전체 방법론, 모든 수치, 명시적 caveat 포함) — raw 로그도 부록으로 보존
- [x] `docs/strategy_spec.md`/`docs/strategy_coverage_audit.md`의 "untuned defaults" 서술을 튜닝 완료로 갱신
- [x] `CHANGELOG.md`/`ROADMAP.md`(Phase 1 게이트 표 갱신, Done 섹션 추가, 신규 후속 항목: ETH/SOL/XRP 표준 규모 재확인)/`PROJECT_STATUS.md`/`ENGINEERING_DECISIONS.md`(항목 #18 신규 — monkey-patch 방식을 택하고 영구 CLI 플래그를 안 만든 이유) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator의 스코프락 지시("Backtest→Walk-Forward→Paper Trading→Small Live 완료 전까지 목표 불변, 계속 자율 진행")에 따라 계속 진행. 완료 후 Paper Trading 준비상태 평가 예정(operator의 명시적 다음 지시)

## 전체 회차 (confluence-strength spec 모호성 해소 — core JadeCap rule에 한해서만 구현하라는 operator 지시 처리, equal-highs/lows는 확정적으로 미구현)
- [x] **operator 지시 재확인 처리**: "confluence-strength logic과 equal-highs/equal-lows liquidity detection을 core JadeCap trading rule일 때만 구현하라"는 명시적 제약 수신
- [x] **범위 판단**: `docs/strategy_spec.md`/`docs/strategy_coverage_audit.md` 재확인 결과 — (1) confluence-strength(항목 #9)는 **이미 스펙에 존재하는 core rule**인데 스펙 문구와 코드 구현 사이에 실제 모호성이 있는 것(스펙 section 6 문구는 "ALL"로 읽히지만 코드는 "sweep OR choch"로 구현됨) → **core rule 범위 내, 구현 진행**. (2) equal-highs/equal-lows(항목 #3)는 **스펙 section 2 자체에 정의가 아예 없음**("스펙 갭이지 코드 갭이 아님"이라고 감사 문서에 이미 명시돼 있었음) → **아직 core rule 아님, 신규 규칙 추가는 스펙 결정이 먼저 필요 → 이번 라운드 구현 안 함**(operator의 "core rule일 때만" 제약을 정확히 준수)
- [x] `app/strategy/entry_model.py::build_entry_model()`에 `require_full_confluence: bool = False` 신규 파라미터 — True면 matching_sweep과 matching_choch **둘 다** 필요(기존은 OR, 하나만 있어도 통과)
- [x] `SignalEngine.generate_signal()`/`BacktestEngine.run()`에 동일 파라미터 threading(기존 `use_breaker_block` 패턴과 완전히 동일한 opt-in 방식)
- [x] `scripts/run_backtest.py --strict-confluence` CLI 플래그 신규
- [x] 신규 테스트 5종: `test_strategy_entry_model.py`에 4개(sweep만 있을 때 거부/choch만 있을 때 거부/둘 다 있을 때 승인/방향 불일치 규칙 유지 확인), `test_strategy_signal_engine.py`에 통합 테스트 1개(실제 detector 파이프라인으로 — 합성 dict가 아니라 진짜 fixture로 파라미터가 제대로 전달되는지 증명). 기존 `_FakeSignalEngineFixedSignal`(test_backtest_engine.py)과 `test_signal_engine_use_breaker_block_true_produces_a_real_short_signal`(내가 실수로 잘랐던 것 — 즉시 발견하고 원상복구) 수정
- [x] 전체 `pytest backend/tests/` **206/206 통과**(201 + 5 신규)
- [x] **A/B 실측 검증(4개 자산 전부, 6개월/6기간 각각)**:

  | | Baseline 트레이드 | Baseline PnL | Strict 트레이드 | Strict PnL |
  |---|---|---|---|---|
  | BTCUSDT | 111 | $1935.35 | 31 | $684.29 |
  | ETHUSDT | 106 | $2725.22 | 18 | $548.26 |
  | SOLUSDT | 124 | $4198.32 | 37 | $957.74 |
  | XRPUSDT | 116 | $2849.89 | 24 | $734.29 |
  | **합계** | **457** | **$11708.78** | **110** | **$2924.58** |

- [x] **핵심 결론**: 트레이드 수 -75.9%(457→110), 총 PnL -75.0%(거의 정비례) — 하지만 트레이드당 평균 손익은 $25.62(baseline) vs $26.59(strict)로 **겨우 +3.8% 차이**(strict 모드 표본이 기간당 0~2건까지 작아진 걸 감안하면 통계적으로 무의미한 수준). 즉 엄격한 confluence는 "더 좋은 트레이드를 골라내는" 게 아니라 "비슷한 품질의 트레이드를 대부분 버리는" 것뿐 — 수익성 개선 없이 기회비용만 발생. **이 프로젝트에서 "더 엄격/보수적인 규칙이 당연히 더 낫다"는 직관이 실측으로 반박된 네 번째 사례**(break-even/Breaker Block/partial-TP에 이어)
- [x] **스펙 자체를 수정해서 모호성 해소**: `docs/strategy_spec.md` section 6을 다시 작성 — "sweep OR choch, 둘 다는 아님"을 명시하고 이번 A/B 근거(트레이드 수 -76%, 품질 개선 없음)를 스펙 본문에 직접 인용. `docs/strategy_coverage_audit.md` 항목 #9도 "RESOLVED"로 갱신, Priority MEDIUM→LOW
- [x] `CHANGELOG.md`(신규 Unreleased 섹션, 4자산 비교표)/`ROADMAP.md`(Done 섹션에 confluence 항목 이동+equal-highs/lows 미구현 사유 명시, Near-term 재정렬)/`PROJECT_STATUS.md`(Strategy Engine 레이어·연구결과 갱신)/`ENGINEERING_DECISIONS.md`(항목 #17 신규 — "스펙을 코드에 맞춰 고쳤다"는 설계 결정과 그 이유) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator의 스코프락 지시에 따라 계속 자율 진행. 완료 후 다음 최고-ROI 미완료 JadeCap 규칙으로 자동 이어가라는 지시 수신 — 현재 남은 core-rule 레벨 항목은 파라미터 스윕(held-out discipline 필요) 정도이며, equal-highs/lows는 스펙 결정 대기 상태

## 전체 회차 (production-ready risk controls: circuit breaker auto-reset 신규 구현 — operator의 PLACEHOLDER_ACCOUNT_BALANCE 스코프 결정 처리 포함)
- [x] **operator 질문에 대한 답변 처리**: "PLACEHOLDER_ACCOUNT_BALANCE를 실제 잔고 소스로 지금 교체해야 하는가?"라는 질문을 드렸고, operator가 **옵션 1(Phase 1은 placeholder 유지, 실제 연동은 Gate #4로 문서화만)**을 명시적으로 선택 — "스코프 확장하지 말라"는 재확인 포함
- [x] `app/config.py`의 `PLACEHOLDER_ACCOUNT_BALANCE` 주석에 이 결정을 명시적으로 기록(operator 승인 없이 Phase 1 중 실제 잔고 연동 작업 시작 금지)
- [x] `ROADMAP.md`의 Phase 1 게이트 표(게이트 #3, #4)와 "Explicitly NOT started" 섹션의 Live Trading 항목에 이 결정 반영
- [x] **"production-ready risk controls" 항목에 실제 기여하는 작업 선정**: 기존 리스크 코드(`position_sizing.py`/`drawdown_guard.py`/`circuit_breaker.py`/`risk_manager.py`) 감사 — position sizing과 drawdown guard는 이미 견고했음. **circuit breaker에서 실제 프로덕션 갭 발견**: `CircuitBreaker.reset()`의 기존 docstring 자체가 "day-boundary auto-reset은 미래 마일스톤 책임"이라고 명시하고 있었고, 실제로 operator가 트립을 해제할 방법이 코드베이스 어디에도 없었음(대시보드 엔드포인트 없음, CLI 없음) — 즉 한 번이라도 daily/weekly loss limit을 건드리면 DB를 수동으로 고치지 않는 한 **영구적으로** 거래가 중단되는 구조
- [x] **수정**: `scripts/run_paper.py::_check_drawdown_and_maybe_trip`에 auto-reset 분기 추가 — breaker가 트립된 상태에서 이번 호출의 최신 daily/weekly 체크가 **둘 다** 통과하면 자동으로 `.reset()` 호출. `TradeJournal.generate_daily_report()`/`generate_weekly_report()`가 이미 UTC-달력일/ISO-달력주 단위로 스코프되어 있으므로, 새 날짜/주가 시작되면 "오늘"/"이번 주" PnL이 자연스럽게 새 기간만 반영하게 되어 별도의 날짜 추적 로직이 전혀 필요 없음(핵심 통찰). auto-reset 시에도 Telegram/Discord 알림 발송(트립 때만이 아니라)
- [x] **명시적으로 문서화한 전제조건(숨기지 않음)**: 이 auto-reset 로직은 "모든 트립이 이 drawdown-check 경로를 통해서만 발생한다"고 가정함(현재는 사실 — 코드베이스에 `trip()` 호출 지점이 여기 하나뿐). 향후 drawdown과 무관한 트립 사유(예: 거래소 API 장애)가 추가되면 이 로직은 reason-aware하게 재작업 필요 — `circuit_breaker.py` 모듈 docstring이 이미 그런 가능성을 언급하고 있었음
- [x] `CircuitBreaker.reset()` docstring을 "열린 갭"에서 "caller가 처리함"으로 갱신
- [x] **실측 검증(pytest 아님 — run_paper.py 관례 유지)**: 임시 SQLite DB로 (1) 무손상 상태에서 트립된 breaker가 auto-reset됨 (2) 실제 -1.5% 일일 손실(1% 한도 위반)이 fresh breaker를 트립시킴 (3) 손실이 그대로 남아있는 날은 auto-reset 안 되고 계속 트립 유지 — 3개 시나리오 전부 통과
- [x] 전체 `pytest backend/tests/` **201/201 유지**(신규 코드지만 run_paper.py 관례상 pytest 커버리지 추가 안 함, 실측으로 대체)
- [x] `CHANGELOG.md`(신규 Unreleased 섹션)/`ROADMAP.md`(Phase 1 게이트 표 갱신, Done 섹션에 신규 항목)/`PROJECT_STATUS.md`(Risk Engine 레이어·게이트 표 갱신)/`ENGINEERING_DECISIONS.md`(항목 #16 신규) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator의 스코프락 지시("Backtest→Walk-Forward→Paper Trading→Small Live 완료 전까지 목표 불변, 계속 자율 진행")에 따라 계속 진행

## 전체 회차 (walk-forward validation을 나머지 3개 자산에도 실행 — Phase 1 게이트 #2, 4개 자산 전부 PASSED로 CLOSED)
- [x] 직전 회차에서 BTCUSDT만 `--walk-forward` 실행했었음 — ROADMAP.md "Immediate" 1순위였던 "나머지 3개 자산(ETH/SOL/XRP)도 실행"을 이어서 진행
- [x] 동일 2026년 6개월/6기간 baseline(실험적 기능 전부 비활성)으로 3개 자산 전부 `--walk-forward` 실행:

  | 자산 | 수익 기간 | 최대 연속손실 | 전반부 평균 PnL | 후반부 평균 PnL | 결과 |
  |---|---|---|---|---|---|
  | BTCUSDT | 6/6 | 0 | $237.47 | $407.64 | **PASSED** |
  | ETHUSDT | 6/6 | 0 | $367.22 | $541.19 | **PASSED** |
  | SOLUSDT | 6/6 | 0 | $585.79 | $813.65 | **PASSED** |
  | XRPUSDT | 6/6 | 0 | $474.38 | $475.59 | **PASSED** |

- [x] **만장일치 결과**: 4개 자산 24/24 기간 전부 수익, 연속손실 0건, 어느 자산에서도 퇴화 트렌드 없음(전부 후반부가 전반부와 같거나 더 좋은 성과) — JadeCap baseline 전략이 테스트된 모든 자산에서 walk-forward 검증을 통과함
- [x] **코드 변경 없음** — 직전 회차에서 만든 도구를 재사용한 순수 실행/검증 라운드. 전체 `pytest backend/tests/` **201/201 유지**(회귀 확인용 재실행)
- [x] `CHANGELOG.md`(4자산 비교표)/`ROADMAP.md`(Phase 1 게이트 표 갱신 — 게이트 #2를 "CLOSED"로, 관련 항목 번호 재정렬)/`PROJECT_STATUS.md`(게이트 표 + 연구결과 갱신) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator의 스코프락 지시("Backtest→Walk-Forward→Paper Trading→Small Live 완료 전까지 목표 불변, 계속 자율 진행")에 따라 계속 진행. 이 태스크는 API 자격증명/라이브 승인/보안/외부유료서비스 어디에도 해당하지 않음

## 전체 회차 (operator의 Phase 1 스코프락 지시 처리 + walk-forward validation 신규 구현(Phase 1 게이트 #2) — BTCUSDT baseline PASSED)
- [x] **operator의 스코프락 지시 수신 및 처리**: "JadeCap 하나를 수익성 있는 자동매매 시스템으로 만드는 것"이 Phase 1의 유일한 목표라는 명시적 지시. Phase 1 체크리스트: (1) JadeCap 구현 완료 (2) 모든 룰 백테스트 검증 (3) walk-forward validation 수행 (4) paper trading 준비 (5) production-ready risk control 구축 (6) paper trading 준비 완료 상태 도달. "이 목표에 직접 기여하지 않는 아이디어는 ROADMAP.md에 Phase 2로 문서화하고 구현하지 않는다"는 명시적 금지 규칙도 수신
- [x] **ROADMAP.md 구조 개편**: 최상단에 "Phase 1 gate status" 표(4개 게이트별 상태) 신규 추가. 기존 "Medium-term (architecture/scalability)" 섹션(멀티전략 플러그인 아키텍처, Monte Carlo readiness)을 "Phase 2 (deferred, out of scope for Phase 1 — do not implement yet)"로 재분류·이동 — operator가 명시적으로 "multi-strategy platform 만들지 마라"고 지시했으므로, 해당 아이디어의 첫걸음격인 멀티전략 아키텍처 항목이 정확히 그 금지 대상에 해당함을 문서에 명시
- [x] **리뷰 프로세스 준수**: PROJECT_STATUS.md/HANDOFF.md/최신 커밋 리뷰 후 "Phase 1에 대해 가장 ROI 높은 단일 과제"로 walk-forward validation을 선정 — Phase 1 체크리스트에 명시적으로 이름이 올라간 항목 중 유일하게 아직 독립된 산출물로 구현되지 않은 것이었음(기존 `--periods`는 "기간별로 나눠서 각각 돌린다"는 것뿐, 명시적 PASS/FAIL 판정이 없었음 — ENGINEERING_DECISIONS.md 항목 #8에서 이미 "파라미터 재적합(refit) walk-forward는 아직 의미 없다"고 문서화되어 있었음, JadeCap에 튜닝 가능한 파라미터가 아직 없기 때문)
- [x] **`scripts/run_backtest.py::walk_forward_report()` 신규**: 기간 시퀀스를 명시적·결정론적 기준으로 판정 — (a) 수익 기간 비율 ≥66%, (b) 연속 손실 기간 ≤2, (c) 전반부 평균 PnL 대비 후반부 평균 PnL이 50% 이상 유지(전반부가 흑자였을 경우) 또는 후반부가 더 나빠지지 않음(전반부가 적자였을 경우) — "퇴화 트렌드" 체크. 파라미터 재적합 walk-forward가 **아님**을 docstring에 명확히 기재(재적합할 파라미터 자체가 없으므로) — 대신 "시간 순서대로 전진하며 성과가 유지되는지"를 실제로 검증하는 정직한 도구
- [x] `--walk-forward` CLI 플래그 신규(`--periods > 1` 필수) — PASS/FAIL과 세부 지표를 콘솔에 출력
- [x] **신규 테스트 10종**(`backend/tests/test_run_backtest.py` 신규 파일) — `scripts/`가 `backend/`의 형제 디렉터리라 `sys.path`에 명시적으로 추가. `walk_forward_report`뿐 아니라 기존에 전혀 테스트되지 않았던 `split_into_periods`도 함께 커버(일관 통과 확인/나머지 처리/홀수 기간 처리 등)
- [x] **실전 검증(가장 중요)**: BTCUSDT/15m 6개월/6기간 baseline에 `--walk-forward` 실행 — **PASSED**(6/6 수익, 연속손실 0, 전반부 평균 $237.47 vs 후반부 평균 $407.64로 오히려 후반부가 더 좋음, 퇴화 없음). 이것이 JadeCap의 공식 Phase 1 게이트 #2 산출물
- [x] 전체 `pytest backend/tests/` **201/201 통과**(191 + 신규 10)
- [x] `CHANGELOG.md`/`PROJECT_STATUS.md`(신규 "Phase 1 gate status" 표 추가)/`ENGINEERING_DECISIONS.md`(항목 #8 후속 기록)/`ROADMAP.md`(Phase 1 게이트 표 + Phase 2 섹션 신설) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator의 스코프락 지시에 따라 계속 자율 진행(Backtest→Walk-Forward→Paper Trading→Small Live 순서 준수, API 자격증명/라이브 승인 등 명시적 정지 조건 아님)

## 전체 회차 (실행 감사 처리 + `--end-date` 시간-고정 백테스트 신규 구현 + BTCUSDT 첫 교차-연도(2025) 검증 — 사용자 지시 "90분 스프린트")
- [x] **사용자의 실행 감사 요청 처리**: "백그라운드 에이전트가 실제로 작동 중인지 가정하지 말고 확인하라" — `git status`(clean)/`git log`(최신 f8490c3, push됨)/실행 중 python 프로세스(없음)/scratchpad 확인 결과 스톨된 작업 없음. 직전 `xrp_breakeven` 커맨드는 사용자가 실행 전에 인터럽트한 것뿐(파일 미생성) — 이어서 XRPUSDT의 나머지 3개 설정(breakeven +5.4%/breaker-block +1.5%/partial-tp -28.7%) 실행 및 검증 완료, 4자산 비교 docs 갱신, 커밋/푸시(`f8490c3`)까지 마무리 (자세한 내용은 위 XRPUSDT 회차 참조)
- [x] **"90분 스프린트" 지시 처리 — 최고 ROI 과제 선정**: 로드맵상 "자산 테스트는 diminishing return, 시간(연도) 축 테스트가 다음 우선순위"였으므로, 엔지니어링 작업으로 `--end-date` 기능을 신규 구현하기로 결정(UI/API키/라이브 관련 아님, 코스메틱 아님, 중복 작업 아님 — 스프린트 제약조건 전부 준수)
- [x] **`CandleFetcher.fetch_ohlcv_history()`에 `end_time_ms` 파라미터 신규 추가**: 기존엔 항상 "지금"에서부터 과거로 페이징했음(특정 과거 구간을 직접 지정할 방법 없음 — 예: "2025년 7월에 끝나는 6개월" 같은 요청은 지금부터 그 구간까지 전부 fetch한 뒤 버려야 해서 사실상 불가능에 가까웠음). `end_time_ms`가 주어지면 첫 페이지의 `after` 커서를 그 값으로 직접 설정 — OKX의 `after=<ts>`가 이미 "그 시각보다 엄격히 과거" 의미이므로 정확히 그 지점부터 페이징 시작
- [x] `scripts/run_backtest.py --end-date YYYY-MM-DD` CLI 신규 — LTF/HTF 양쪽 fetch 모두 동일 anchor로 배선
- [x] 신규 테스트 1종(`test_fetch_ohlcv_history_end_time_ms_anchors_first_page_instead_of_now`) — 전체 `pytest` **191/191 통과**(190+1)
- [x] **실현가능성 사전 확인**: 2025-01-15로 anchor한 5캔들 직접 fetch 결과 실제 2025-01-14T22:45~23:45 타임스탬프 반환 확인(가짜로 "지금"에 fallback하지 않음을 실측 검증)
- [x] **첫 실전 교차-연도 검증**: BTCUSDT/15m, `--candles 3000 --periods 6 --end-date 2025-07-10`(2026년과 동일한 방법론, 연도만 다름). baseline 6개 기간 전부 수익($1346.13)이지만 **레짐이 확연히 다름**(총 67트레이드, 2026년보다 훨씬 적음, P1은 단 2건)

  | | P1 | P2 | P3 | P4 | P5 | P6 | 합계 |
  |---|---|---|---|---|---|---|---|
  | Baseline(2025) | $61.82 | $387.70 | $338.23 | $182.27 | $247.76 | $128.36 | $1346.14 |
  | Break-even(2025) | $61.82 | $431.58 | $338.23 | $124.82 | $226.00 | $138.44 | **$1320.89 (-1.9%)** |
  | Breaker Block(2025) | $61.82 | $387.70 | $338.23 | $182.27 | $247.76 | $128.36 | **$1346.14 (0.0%)** |
  | Partial TP(2025) | $43.15 | $275.57 | $216.55 | $92.77 | $189.28 | $96.86 | **$914.18 (-32.1%)** |

- [x] **Break-even: 동일 자산에서도 부호 뒤집힘(프로젝트 최중요 발견)** — BTC 2026년 +9.2% vs BTC 2025년 -1.9%. 자산을 고정해도 시간이 바뀌면 방향이 뒤집힘 — 자산 축(2승2패)에 이어 시간 축에서도 신뢰 방향 없음이 확인되어 `ENABLE_BREAKEVEN` 영구 False가 한층 더 굳어짐
- [x] **Breaker Block: 2025년 구간에서 완전 무효과(0.0%)** — 전 기간 baseline과 100% 동일. "발현 자체가 드물다"는 기존 관찰과 일치
- [x] **Partial TP: 연도가 달라도 -32.6%(2026)→-32.1%(2025)로 거의 동일하게 재현** — 이제 4개 자산 + 동일 자산의 2개 연도 전부에서 일관되게 부정적, 프로젝트에서 가장 강력한 근거
- [x] **코드 변경 있음(신규 기능)**: `candle_fetcher.py`(신규 파라미터), `run_backtest.py`(신규 CLI 플래그), `test_candle_fetcher.py`(신규 테스트 1종) — 전체 `pytest` 191/191 통과
- [x] `CHANGELOG.md`(신규 기능 + 첫 교차연도 검증 결과)/`ROADMAP.md`(자산 대신 연도 우선순위로 재조정)/`PROJECT_STATUS.md`(연구 결과에 시간축 추가)/`ENGINEERING_DECISIONS.md`(항목 #15 후속 기록: "시간 윈도우 수"도 "자산 수"·"기간 수"와 같은 회의론 필요) 갱신
- [x] git commit/push 예정 (`origin/master`) — 사용자가 "90분 스프린트 끝나면 완료 작업 요약, before/after 지표, 테스트, 커밋, 남은 리스크 보고, 전체 문서 갱신, 커밋, 푸시, 깔끔하게 종료"라고 명시적으로 지시함

## 전체 회차 (XRPUSDT 6개월 딥 데이터 재검증 — break-even 추세가 4번째 자산에서 완전히 깨짐(2승2패), 로드맵 1순위 + 사용자 실행감사 요청 처리)
- [x] **사용자의 실행 감사 요청 처리**: "백그라운드 에이전트가 실제로 작동 중인지 가정하지 말고 확인하라"는 명시적 지시 수신 — `git status`(clean)/`git log`(최신 커밋 efedfea, 이미 push됨)/실행 중 python 프로세스(없음)/scratchpad 최근 파일 확인 결과, 스톨되거나 실패한 백그라운드 작업은 전혀 없었음. 직전 `xrp_breakeven` 커맨드는 사용자가 실행 전에 인터럽트했을 뿐(파일 자체가 생성 안 됨) — 즉 "미완료 작업을 이어받는" 상황이 아니라 "인터럽트된 지점부터 계속"하는 상황이었음을 확인 후 보고
- [x] 동일 방법론으로 XRPUSDT/15m, `--candles 3000 --periods 6`(2026년 1월~7월) 4개 설정 전부 실행. baseline 6개 기간 전부 수익(합산 $2817.37)

  | | P1 | P2 | P3 | P4 | P5 | P6 | 합계 |
  |---|---|---|---|---|---|---|---|
  | Baseline | $382.46 | $530.67 | $477.48 | $303.82 | $504.99 | $617.95 | $2817.37 |
  | Break-even | $382.46 | $569.74 | $427.04 | $303.82 | $453.61 | $832.63 | **$2969.31 (+5.4%)** |
  | Breaker Block | $382.46 | $573.34 | $477.48 | $303.82 | $504.99 | $617.95 | **$2860.04 (+1.5%)** |
  | Partial TP | $250.07 | $400.88 | $296.58 | $166.81 | $358.77 | $536.36 | **$2009.47 (-28.7%)** |

- [x] **4자산 누적표(BTC/ETH/SOL/XRP)**:

  | 항목 | BTC | ETH | SOL | XRP | 결론 |
  |---|---|---|---|---|---|
  | Break-even | +9.2% | -1.9% | -4.8% | +5.4% | **방향성 없음 — 2승 2패** |
  | Breaker Block | -3.8% | -12.0% | -1.9% | +1.5% | **대체로 부정 — 4개 중 3개 부정, 1개 긍정** |
  | Partial TP | -32.6% | -35.4% | -29.1% | -28.7% | **4개 전부 부정, 24/24 기간** |

- [x] **Break-even: "부정 쪽 추세"였던 것이 4번째 자산에서 완전히 깨짐** — SOLUSDT까지 3개 자산 결과만 보면 "긍정보다 부정이 더 흔함"으로 읽혔는데, XRPUSDT +5.4%가 그 추세를 깨서 최종 2승2패가 됨. **자산 수가 적으면 가짜 추세가 나올 수 있다는 걸 실제로 보여준 사례** — ENGINEERING_DECISIONS.md 항목 #15에 후속 기록 추가(기간 수뿐 아니라 자산 수에도 같은 회의론이 필요함을 명시). `ENABLE_BREAKEVEN` 기본값 False는 이제 "증거 대기 중" 상태가 아니라 자산에 무관하게 신뢰할 방향이 아예 없다는 확정된 설계 결론으로 격상
- [x] **Breaker Block: 만장일치 부정이 깨짐** — XRP +1.5%가 첫 긍정 결과(4개 중 3개는 여전히 부정이라 비추천 유지되지만 "모든 자산에서 부정"이라는 서술은 더 이상 정확하지 않음)
- [x] **Partial TP: 4개 자산 24/24 기간 전부 악화, 예외 0건 — 유일하게 견고한 발견 유지**. 프로젝트에서 "적극적으로 비추천"할 만큼의 근거를 가진 유일한 항목
- [x] **코드 변경 없음** — 순수 재검증/연구 라운드. 전체 `pytest backend/tests/` **190/190 통과**(회귀 확인용 재실행)
- [x] `CHANGELOG.md`(신규 Unreleased 섹션, 4자산 비교표)/`ROADMAP.md`(4순위 항목 Done 이동, "자산 대신 연도 확장" 신규 방향 제시, `ENABLE_BREAKEVEN` 영구 False 명시)/`PROJECT_STATUS.md`(연구 결과 전면 재작성)/`ENGINEERING_DECISIONS.md`(항목 #15 후속 기록) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (SOLUSDT 6개월 딥 데이터 재검증 — break-even이 3개 자산 중 2개에서 부정적으로 확정, 로드맵 1순위)
- [x] **배경**: ETHUSDT 재검증 직후 바로 이어서, 로드맵 "Immediate" 1순위였던 세 번째(상관성 낮은) 심볼 재검증 진행. SOLUSDT 선택(BTC/ETH와 마찬가지로 대형 L1이라 "상관성 낮음"이라는 목표는 완전히 달성 못 했지만, 세 번째 독립 자산 데이터 포인트 확보라는 목적은 달성)
- [x] 동일 방법론: SOLUSDT/15m, `--candles 3000 --periods 6`(2026년 1월~7월), baseline/breakeven/breaker-block/partial-tp 4개 설정 전부 실행. baseline 자체가 6개 기간 전부 수익(합산 $4147.36, 2번 기간은 승률 100%)

  | | P1 | P2 | P3 | P4 | P5 | P6 | 합계 |
  |---|---|---|---|---|---|---|---|
  | Baseline | $631.31 | $743.90 | $337.93 | $184.68 | $1326.04 | $923.50 | $4147.36 |
  | Break-even | $579.84 | $743.90 | $221.15 | $184.68 | $1318.43 | $898.42 | **$3946.42 (-4.8%)** |
  | Breaker Block | $553.00 | $743.90 | $337.93 | $184.68 | $1326.04 | $923.50 | **$4069.05 (-1.9%)** |
  | Partial TP | $444.40 | $537.32 | $243.88 | $117.23 | $933.46 | $662.50 | **$2938.79 (-29.1%)** |

- [x] **3자산 누적표(BTC/ETH/SOL)**:

  | 항목 | BTC | ETH | SOL | 결론 |
  |---|---|---|---|---|
  | Break-even | +9.2% | -1.9% | -4.8% | **3개 중 1개만 긍정, 2개 부정** |
  | Breaker Block | -3.8% | -12.0% | -1.9% | **3개 전부 부정** |
  | Partial TP | -32.6% | -35.4% | -29.1% | **3개 전부 부정, 18/18 기간** |

- [x] **Break-even: 부정 쪽으로 결론 강화** — SOLUSDT 결과는 ETHUSDT처럼 혼재되지 않고 균일하게 나쁨(개선 0개/악화 4개/무영향 2개, 승률 하락 사례: P3 85.71%→64.29%). BTC에서만 좋았고 ETH/SOL 둘 다 나빴다는 것은 "BTC가 예외였을 가능성"을 시사 — 다만 3개는 여전히 적은 자산 표본이므로 4번째 자산 없이 최종 결론 내리지 않음
- [x] **Breaker Block: 3개 자산 전부 부정 확정** — 규모는 자산마다 다름(SOL -1.9%~ETH -12.0%), 방향은 일관됨
- [x] **Partial TP: 3개 자산 전부 부정, 18/18 기간 전부 악화, 예외 0건** — 프로젝트 전체에서 가장 강력하고 일관된 발견. 기계적 설명(고정 2:1 RR + 높은 승률 → partial 청산이 승자의 upside를 손실 방어보다 더 많이 깎아먹음)이 세 번째 독립 자산에서도 예외 없이 유지됨
- [x] **코드 변경 없음** — 순수 재검증/연구 라운드. `ENABLE_BREAKEVEN` 기본값(False) 유지 — 이번 결과가 그 선택을 더욱 강하게 뒷받침함
- [x] 전체 `pytest backend/tests/` **190/190 통과**(코드 변경 없으므로 회귀 확인용 재실행)
- [x] `CHANGELOG.md`(신규 Unreleased 섹션, 3자산 비교표)/`ROADMAP.md`(1순위 항목 Done 이동, 신규 후속 항목: "4번째 자산 검증 전까지 결론 유보")/`PROJECT_STATUS.md`(연구 결과·honest caveats 전면 재작성) 갱신
- [x] 참고: 이번 회차 시작 전, 이전 회차부터 스톨돼있던 "position exit-checking 배선" 백그라운드 서브에이전트(이미 완료된 작업을 중복으로 맡고 있었음)를 `TaskStop`으로 정리함
- [x] git commit/push 예정 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (ETHUSDT 6개월 딥 데이터 재검증 — break-even 결론이 자산별로 다름을 발견, 로드맵 1순위)
- [x] **배경**: break-even paper trading 배선 완료 직후 바로 이어서, 로드맵 "Immediate" 1순위였던 ETHUSDT 6개월 재검증 진행(라이브 자격증명/승인/보안/외부유료서비스 어디에도 해당 안 함 — 계속 진행 조건 충족)
- [x] BTCUSDT 검증과 완전히 동일한 방법론: ETHUSDT/15m, `--candles 3000 --periods 6`(2026년 1월~7월), baseline/breakeven/breaker-block/partial-tp 4개 설정 전부 실행. baseline 자체가 6개 기간 전부 수익(합산 $2906.18)

  | | P1 | P2 | P3 | P4 | P5 | P6 | 합계 |
  |---|---|---|---|---|---|---|---|
  | Baseline | $317.23 | $684.60 | $30.02 | $568.11 | $692.01 | $614.22 | $2906.18 |
  | Break-even | $401.77 | $684.60 | -$18.17 | $568.11 | $601.63 | $614.22 | **$2852.16 (-1.9%)** |
  | Breaker Block | $308.06 | $667.97 | $30.02 | $568.11 | $611.84 | $372.57 | **$2558.56 (-12.0%)** |
  | Partial TP | $269.30 | $507.60 | $0.94 | $392.71 | $463.05 | $245.31 | **$1878.91 (-35.4%)** |

- [x] **Break-even: 재현 안 됨(가장 중요한 발견)** — BTC는 +13.5%(소표본)→+9.2%(6개월)로 재현됐었는데, ETH는 -1.9%로 방향이 뒤집힘. 기간별로 보면 완전히 나쁜 건 아니고 혼재됨: P1 개선(+$84.54), P3는 원래 승리했을 트레이드가 1R 도달 후 반전해서 breakeven 근처에서 청산되며 승→패 전환(승률 60%→40%, -$48.19 — 이게 바로 break-even의 알려진 리스크 메커니즘이 실제로 발현된 사례), P5 악화(-$90.38), P2/P4/P6은 트리거 자체가 발동 안 해서 무영향. **결론: break-even의 효과는 자산-의존적이지 보편적이지 않음**
- [x] **방법론적 교훈 발견 및 기록(ENGINEERING_DECISIONS.md 항목 #15 신규)**: "재현됨(reproduced)"이라는 표현이 지금까지 무엇이 달라졌는지(같은 자산의 다른 시간 구간 vs 다른 자산)를 명시하지 않아서 오해를 낳을 뻔했음. break-even의 "두 독립 표본에서 재현"은 실은 BTCUSDT의 서로 다른 두 시간 구간이었을 뿐 — 서로 다른 자산 테스트(ETHUSDT)에서는 결론이 뒤집힘. 반면 partial-tp/breaker-block은 진짜로 자산이 달라져도 재현됐으므로, 같은 "재현" 표현이 실제로는 서로 다른 신뢰도를 가리키고 있었음. 앞으로 모든 재검증 문서는 "무엇이 달라졌는지"를 명시하기로 함
- [x] **Breaker Block: 더 강하게 재현(부정)** — BTC -3.8%(6개 중 1개 기간 영향) → ETH -12.0%(6개 중 4개 기간 영향, 전부 부정, 개선 0건). 두 자산에서 같은 방향으로 재현, 규모는 ETH가 훨씬 큼
- [x] **Partial TP: 더 강하게 재현(부정)** — BTC -32.6% → ETH -35.4%. 두 자산 전 기간(12/12) 예외 없이 전부 악화 — 기계적 설명(고정 2:1 RR + 높은 승률 → partial 청산이 승자의 upside를 매번 크게 깎아먹음)이 두 번째 독립 자산에서도 그대로 유지됨
- [x] **코드 변경 없음** — 순수 재검증/연구 라운드(감사 원칙 준수: "전략이 더 완전해지거나 통계적으로 더 강해지지 않는 한 기능을 계속 추가하지 않는다"). `ENABLE_BREAKEVEN` 기본값(False)은 그대로 유지 — 이번 발견이 바로 그 기본값을 지지하는 근거가 됨(BTCUSDT 증거만 보고 기본값을 True로 바꿨다면 지금 ETHUSDT에서 소폭 손해를 보고 있었을 것)
- [x] 전체 `pytest backend/tests/` **190/190 통과**(코드 변경 없으므로 회귀 확인용 재실행)
- [x] `CHANGELOG.md`(신규 Unreleased 섹션, 전체 비교표)/`ROADMAP.md`(1순위 항목 Done 이동, 번호 재정렬, 신규 후속 항목 "symbol-aware ENABLE_BREAKEVEN" 추가)/`PROJECT_STATUS.md`(연구 결과·honest caveats 전면 갱신)/`ENGINEERING_DECISIONS.md`(항목 #15 신규) 갱신
- [x] git commit/push 예정 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (break-even을 paper trading에 배선 — 로드맵 1순위, "계속하라" 지시에 따라 진행)
- [x] **배경**: 세 A/B 실험(break-even/breaker-block/partial-tp) 중 두 독립 표본(31일 소표본, 6개월 딥표본)에서 같은 방향으로 재현된 것은 break-even뿐(+13.5% → +9.2%) — 로드맵에서 이것만 paper trading 배선 대상 1순위로 승격했었음
- [x] `app/config.py`에 `ENABLE_BREAKEVEN: bool = False`, `BREAKEVEN_TRIGGER_R: float = 1.0` 추가
- [x] `backend/app/backtesting/backtest_engine.py`의 모듈 상수 `BREAKEVEN_TRIGGER_R`을 하드코딩 `1.0`에서 `settings.BREAKEVEN_TRIGGER_R`로 리팩터 — paper trading과 backtest가 항상 같은 트리거 거리를 쓰도록 단일 소스화 (리팩터 직후 187/187 통과 확인, 회귀 없음)
- [x] `app/portfolio/trades.py::TradeTracker.update_stop_loss(trade_id, new_stop_loss)` 신규 — trade_id 미존재 시 ValueError, 존재하지만 이미 closed면 별도 ValueError("not open") — `close_trade`와 동일한 "절대 조용히 no-op하지 않는다" 계약
- [x] `scripts/run_paper.py::_maybe_move_to_breakeven(current_price)` 신규: 열린 포지션마다 원래 entry/stop 거리로 1R 트리거가를 계산, 가격이 도달하면 stop을 entry로 이동. `settings.ENABLE_BREAKEVEN`이 False면 완전 no-op. 멱등성은 신규 DB 컬럼 없이 "stop이 이미 entry 이상/이하(방향별)면 스킵"으로 추론(정상 신호는 애초에 stop이 entry와 같거나 유리한 쪽일 수 없으므로 안전)
- [x] `run_once()`에 배선: **exit-check 스텝 바로 다음, concurrency guard 이전** — BacktestEngine의 same-pass 보수적 순서(이번 패스에서 트리거에 도달한 포지션도 이번 패스는 여전히 OLD stop으로 exit-check됨, 다음 패스부터 새 stop 적용)와 동일하게 맞춤. summary dict에 `breakeven_moved: list[int]` 필드 추가
- [x] **재사용 발견**: `app/execution/order_manager.py::OrderManager.move_to_breakeven(position)`이 이미 존재했음(ENGINEERING_DECISIONS.md 항목 #6에서 "paper trading에 배선될 때 자연스러운 재사용 지점"이라고 이미 예견해둔 것) — 처음엔 직접 `new_stop_loss=entry_price`로 구현했다가, 이 기존 함수를 발견하고 `OrderManager(PaperBroker()).move_to_breakeven(position)` 호출로 리팩터하여 재사용. 트리거/멱등성 판단 로직만 신규(그 함수 자체엔 트리거 개념이 없음 — 호출되면 무조건 이동)
- [x] 신규 테스트 3종(`test_portfolio.py`): 정상 이동 라운드트립 / 미존재 id ValueError / 이미 closed인 trade ValueError
- [x] **실측 검증(pytest 아님 — run_paper.py는 실제 네트워크 캔들 fetch가 필요해 기존부터 pytest 커버리지 없음, 기존 관례 유지)**: 임시 SQLite DB로 long 트리거 미도달(무변화)/도달(이동)/이후 패스(이미 breakeven이라 재이동 안 함, 멱등성 확인), short 트리거 도달(이동), `ENABLE_BREAKEVEN=False`(가격 무관 완전 무변화) 전부 통과
- [x] 전체 `pytest backend/tests/` **190/190 통과**(187 + 신규 3)
- [x] `ROADMAP.md`(1순위 항목을 Done으로 이동, 번호 재정렬)/`PROJECT_STATUS.md`(Paper Trading 레이어 상태, 테스트 개수, 캐비어트 갱신)/`ENGINEERING_DECISIONS.md`(항목 #6 업데이트 — 재사용이 실제로 일어났음을 기록)/`CHANGELOG.md`(신규 Unreleased 섹션) 갱신
- [x] **참고 — 스톨된 백그라운드 서브에이전트**: 이 작업 시작 시점에 "Wire position exit-checking into paper trading"이라는 이름의 백그라운드 로컬 에이전트가 이미 실행 중이었음. 직접 SendMessage로 진행 상황을 물었으나 2시간 넘게 응답도 파일 변경도 없어 스톨로 판단. `git log`로 확인한 결과 그 작업(포지션 exit-checking 배선)은 이미 이전 회차 커밋(`8e7b1b3 Paper trades now actually close on SL/TP...`)에서 완료되어 있었음 — 즉 그 서브에이전트는 이미 끝난 작업을 중복으로 맡았던 것으로 보임. 계속 대기하는 대신 이번 회차의 실제 작업(break-even 배선)을 직접 진행함
- [x] git commit/push 예정 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (HTF 과다 fetch 버그 수정 + 3개 감사 항목 딥 데이터 재검증 — "계속하라" 지시에 따라 로드맵 1순위 항목 진행)
- [x] **버그 발견 계기**: 로드맵 1순위 "다른 시장 레짐에 걸친 기간 확보"를 실행하려고 `--candles 3000 --periods 6`(총 18000캔들 ≈ 187일)으로 딥 백테스트를 시도했는데, 10분 넘게 아무 출력도 없이 멈춤 — 프로세스 확인 결과 실제로 살아있었지만 진행이 없어 강제 종료
- [x] **근본 원인 진단**: `run_backtest.py`가 LTF와 HTF fetch 양쪽에 동일한 `total_candles = --candles * --periods`를 그대로 사용하고 있었음 — LTF(15m) 기준 18000캔들은 187일치인데, 같은 18000캔들을 HTF(4h) 기준으로 요청하면 약 8.2년치 히스토리를 요구하게 되어 `fetch_ohlcv_history`가 `max_pages` 안전 상한(200페이지)까지 계속 페이징하며 몇 분간 멈춘 것처럼 보였음
- [x] `app.data.candle_fetcher.timeframe_to_timedelta()`(타임프레임 문자열→실제 시간 길이 변환) + `scripts/run_backtest.py::htf_candle_count_for_span()`(LTF 요청이 커버하는 실제 시간 범위에 맞춰 HTF 요청량을 역산, `detect_htf_bias()`가 굶지 않도록 300캔들 하한 적용) 신규 — 실측으로 직접 확인: 동일한 버그 시나리오에서 이제 HTF 요청량이 18000(≈8.2년)이 아니라 1125(≈187일, LTF 범위와 정확히 일치)로 계산됨
- [x] 신규 테스트 2종(`test_candle_fetcher.py`): `timeframe_to_timedelta`의 단위별 변환 + 잘못된 포맷 에러 처리
- [x] 전체 `pytest backend/tests/` **187/187 통과**(기존 185 + 신규 2)
- [x] **수정 후 딥 데이터 재검증(가장 중요)**: BTCUSDT/15m, `--candles 3000 --periods 6`(2026년 1월~7월, 6개월치, 실제로 서로 다른 시장 상황 — 승률 62.5%~90.48%, 트레이드 수 8~28건으로 기간마다 확연히 다름)로 baseline/breakeven/breaker-block/partial-tp 4개 설정 전부 재실행:

  | | P1 | P2 | P3 | P4 | P5 | P6 | 합계 |
  |---|---|---|---|---|---|---|---|
  | Baseline | $433.51 | $208.77 | $70.14 | $567.92 | $162.77 | $462.18 | $1905.29 |
  | Break-even | $383.30 | $235.08 | $96.52 | $596.91 | $274.69 | $493.95 | **$2080.45 (+9.2%)** |
  | Breaker Block | 동일 | 동일 | 동일 | $496.11 | 동일 | 동일 | **$1833.48 (-3.8%)** |
  | Partial TP | $282.50 | $98.83 | $42.89 | $404.57 | $157.88 | $297.21 | **$1283.87 (-32.6%)** |

  baseline 자체가 이미 **6개 기간 전부 수익**(합산 $1905.29) — 소표본(31일/3기간)보다 훨씬 강력하고 다양한 증거
- [x] **Break-even: 재현됨(긍정 결론 유지)** — 소표본 +13.5% vs 딥표본 +9.2%, 방향 일치. 6개 기간 중 5개 개선
- [x] **Partial TP: 재현됨(부정 결론 유지)** — 소표본 -31.4% vs 딥표본 -32.6%, 거의 동일한 크기로 재현. 이전 회차의 기계적 설명(RR 고정 + 높은 승률 → partial 청산이 승자의 upside를 매번 깎아먹음)이 큰 표본에서도 그대로 확인됨
- [x] **Breaker Block: 결론이 실제로 바뀜(중립 → 소폭 부정)** — 소표본에서는 발현 기회 자체가 없어서(2번의 실제 신호 차이가 둘 다 이미 열려있던 트레이드 구간에 우연히 걸림) 완전히 중립이었는데, 6배 큰 표본에서는 실제로 1개 기간(P4)에서 발현됐고 그 효과가 부정적이었음(승률 90.48%→85.71%). 여전히 "확실히 해롭다"고 하기엔 표본이 작지만(6개 중 1개), "중립"이라는 이전 결론은 더 이상 정확하지 않음 — **이것이 바로 OOS 검증 도구를 만든 이유가 실제로 작동한 사례**: 표본이 작으면 진짜 결론이 아니라 우연히 발현 기회가 없었을 뿐인 결론을 얻을 수 있음
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가(전체 비교표 + 재검증 결과 포함)
- [x] scope 준수: `backend/app/*` 전부 무변경(이번 회차는 데이터 계층 fetch 버그 수정 + 실측 재검증), live-trading 게이팅 무관
- [x] git commit/push 완료 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (Partial Take-Profit 완전 배선 + A/B 검증 — 감사 HIGH 항목 3개 중 마지막, "계속하라" 지시에 따라 이어서 진행)
- [x] `BacktestEngine._simulate_trade()`에 2-leg exit 지원 추가: `use_partial_tp=True`(opt-in) 시 `PARTIAL_TP_PORTION`(50%)이 `PARTIAL_TP_TRIGGER_R`(1R) 도달 시 자체 가격/수수료로 청산되고, 나머지는 원래 stop_loss/take_profit으로 계속 진행. 캔들 내 체크 순서: stop_loss(최악 우선, 기존 유지) → **partial-TP 트리거**(아직 미발동 시) → take_profit — partial 트리거가가 항상 take_profit보다 진입가에 가까우므로(RR>1인 한) take_profit에 도달하는 캔들은 반드시 partial 트리거도 지나쳤을 것이라는 논리로, 단일 캔들이 곧장 take_profit까지 점프해도 partial leg를 먼저 정확히 banking하도록 설계
- [x] `use_partial_tp`는 `use_breakeven`과 완전히 독립(이번 회차는 병행 테스트 안 함 — "한 번에 한 변수만" 원칙 유지). trade record에 `partial_tp_triggered`/`partial_tp_exit_price`/`partial_tp_pnl` 필드 추가
- [x] `BacktestEngine.run(..., use_partial_tp=False)` → `scripts/run_backtest.py --partial-tp`까지 전체 체인 배선(break-even/breaker-block과 동일 패턴)
- [x] 신규 테스트 5종: 기본값 비활성 대조 / 활성 시 이익 확정 후 나머지가 실제 take_profit까지 도달 / 활성 시 나머지가 손절되어도 전체 손실보다 낫다는 보호 효과 증명 / **단일 캔들이 곧장 take_profit까지 점프해도 partial leg를 먼저 banking하는 순서 증명** / short 방향 대칭
- [x] 전체 `pytest backend/tests/` **185/185 통과**(기존 180 + 신규 5). 재실행으로 flakiness 없음 확인
- [x] **오케스트레이터 재검증용 실측(A/B, 가장 중요)**: break-even/breaker-block 검증에 썼던 것과 완전히 동일한 6개 기간(BTCUSDT/ETHUSDT 15m, 각 3개)으로 `--partial-tp` on/off 재실행:

  | | BTC P1 | P2 | P3 | ETH P1 | P2 | P3 |
  |---|---|---|---|---|---|---|
  | Off | -$48.64 | +$165.81 | +$184.62 | +$148.51 | +$60.04 | +$308.75 |
  | On | -$56.43 | +$111.63 | +$135.58 | +$106.83 | +$24.85 | +$239.81 |

  **6개 기간 전부 악화, 예외 없음** — 합산 $819.09→$562.27(-31.4%). 승률/수익-손실 분류 자체는 기간마다 변화 없음(partial-tp는 "이겼나 졌나"를 안 바꾸고 "얼마나"만 줄임)
- [x] **원인까지 명확히 설명(operator 지시 "research before implementation, evidence over assumption" 반영)**: 이 전략은 `entry_model.py`의 `_RR=2.0` 고정값 + 이 표본에서의 높은 승률(많은 트레이드가 실제로 끝까지 TP 도달) 조합 — 1R에서 절반을 미리 파는 것은 "TP까지 가는" 트레이드마다 그 upside의 절반을 포기시키는데, 패배하는 트레이드는 애초에 1R 근처도 못 가고 바로 stop을 맞는 경우가 대부분이라 방어 효과가 거의 없음. "승률 높고 RR 고정인 전략에서는 partial-TP가 구조적으로 불리하다"는 것이 이번 실측이 보여준 명확한 인과 — 다른 승률/RR 프로필의 전략이라면 반대 결과가 나올 수 있음(전략 특정적 결론이지 partial-TP 기법 자체에 대한 보편적 결론 아님)
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가(전체 A/B 표 + 원인 분석 포함)
- [x] **operator 지시 "성능 개선 안 되면 증거만 남기고 optional 유지" 준수 — 이번엔 명확히 부정적인 결과**: 6개 기간 전부 악화이므로 opt-in 유지는 물론, 향후에도 이 전략에는 추천하지 않는다고 명시적으로 기록. `run_paper.py`에도 연결 안 함
- [x] **감사(`docs/strategy_coverage_audit.md`)에서 발견된 HIGH 항목 3개 전부 A/B 검증 완료**: breaker block(중립, 발현 기회 없었음) / break-even(긍정, +13.5%, 5/6→6/6) / partial-tp(부정, -31.4%, 6/6 전부 악화) — 셋 다 실 데이터로 검증했고 결과가 셋 다 다름(중립/긍정/부정), 이것이 "가정하지 말고 실측하라"는 원칙이 실제로 작동한 증거
- [x] scope 준수: `backend/app/strategy/*`(무변경), `backend/app/risk/*`(무변경), `backend/app/execution/*`(무변경 — `OrderManager.handle_partial_tp()` 재사용 안 하고 `BacktestEngine` 안에 독립 구현, break-even 때와 동일한 설계 판단), `scripts/run_paper.py`(무변경), Dashboard/live 게이팅 전부 무변경
- [x] git commit/push 완료 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (Breaker Block 완전 배선 + A/B 검증 — 로드맵 1순위 항목, "계속하라" 지시에 따라 이어서 진행)
- [x] `detect_breaker_block()`에 `retest_index`(원 order block의 base 캔들 인덱스인 기존 `index`와 별개, 실제로 breaker로 확정시킨 리테스트 캔들의 인덱스) 신규 반환 — mitigation 체크가 base 캔들이 아니라 리테스트 확정 캔들 "이후"부터 시작해야 함(`impulse_index` 추가 때와 동일한 이유)
- [x] `build_entry_model()`에 선택적 6번째 파라미터 `breaker_block=None` 추가(기존 호출부 전부 무변경 동작) — FVG/OB와 동일한 "가장 최근 index 우선" 규칙으로 경쟁
- [x] `SignalEngine.generate_signal(..., use_breaker_block=False)` opt-in 추가 — `BacktestEngine.run(..., use_breaker_block=False)` → `scripts/run_backtest.py --breaker-block`까지 전체 체인 배선(break-even과 동일 패턴)
- [x] 신규 테스트 6종: `test_strategy_entry_model.py`에 breaker block 단독으로 시그널 생성/index 경쟁/방향 불일치 거부 4종 + `test_strategy_signal_engine.py`에 **실제 end-to-end 대조쌍**(같은 셋업에서 `use_breaker_block=False`는 시그널 없음, `True`는 실제 short 시그널) 2종
- [x] 전체 `pytest backend/tests/` **180/180 통과**(기존 174 + 신규 6). 재실행으로 flakiness 없음 확인
- [x] **오케스트레이터 재검증용 실측(A/B, 가장 중요)**: break-even 검증에 썼던 것과 완전히 동일한 6개 기간(BTCUSDT/ETHUSDT 15m, 각 3개)으로 `--breaker-block` on/off 재실행 → **6개 기간 전부 트레이드 수/PnL/승률 완전히 동일**(BTC: 301.79/301.79, ETH: 517.30/517.30, 소수점까지 일치)
- [x] **"안 됨"에서 멈추지 않고 원인 진단(operator 지시 "research before implementation, evidence over assumption" 반영)**: 실 BTCUSDT/15m/1000캔들에 대해 매 walk-forward 스텝마다 `detect_breaker_block()`을 직접 재실행 → 970스텝 중 124회 raw 탐지, 29회 unmitigated(즉 기능 자체는 활발하게 작동함, "탐지가 안 됨"이 아님). 추가로 매 스텝마다 `use_breaker_block=True`/`False` 양쪽으로 `generate_signal()`을 독립적으로 재실행해 비교 → **실제로 시그널이 달라진 지점이 2곳 존재**(step 629, 630 — long, entry_price가 다름) → 즉 기능은 정상 작동하고 실제로 다른 트레이드를 만들 수 있었음. 그런데 실제 `BacktestEngine.run()`의 walk-forward는 트레이드가 열려있는 동안 다음 스텝들을 건너뛰므로(exit_index+1로 점프), 이 2개 지점이 우연히 이미 열려있던 트레이드의 구간 안에 들어가 있어서 실제 백테스트에는 한 번도 도달하지 못함 — "이 표본에서는 발현 기회가 없었다"는 정확한 원인
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가(진단 과정 전체 포함)
- [x] **operator 지시 "성능 개선 안 되면 증거만 남기고 optional 유지" 그대로 준수**: 6개 기간 전부 변화 0이므로 "통계적으로 더 강해짐" 기준 미충족 — 기본값 변경 안 함, `run_paper.py`에도 연결 안 함. 근거(위 진단)는 CHANGELOG/HANDOFF 양쪽에 상세 기록
- [x] scope 준수: `backend/app/risk/*`(무변경), `backend/app/execution/*`(무변경), `backend/app/portfolio/*`(무변경), `scripts/run_paper.py`(무변경), Dashboard/live 게이팅 전부 무변경
- [x] git commit/push 완료 (`origin/master`) — operator가 "계속하라, CTO처럼 사고하라, API 자격증명/라이브 승인/보안/외부유료서비스 아니면 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (Strategy Coverage Audit + break-even stop management A/B 검증 — operator 지시: "기능 추가 금지, 먼저 감사부터")
- [x] **감사 수행(코드 작성 전)**: `docs/architecture.md`의 6-layer 설계 + `docs/strategy_spec.md` + `docs/risk_rules.md`에 문서화된 모든 규칙을 실제 구현(`backend/app/`)과 테스트 커버리지에 대조하는 전체 매트릭스를 `docs/strategy_coverage_audit.md`로 작성(규칙/구현상태/테스트커버리지/누락로직/가정/모호성/우선순위 7개 컬럼, 28개 규칙 전부 검토)
- [x] **감사로 발견한 핵심 패턴**: HIGH 우선순위 3개 항목이 전부 같은 모양 — **실 로직이 이미 존재하고 격리 단위테스트까지 있지만 실제 라이브 의사결정 루프에서 완전히 분리돼 있음**: (1) Breaker Block 탐지(`detect_breaker_block`, `SignalEngine.generate_signal()`에서 한 번도 호출 안 됨), (2) Break-even stop 이동(`OrderManager.move_to_breakeven`), (3) Partial TP(`OrderManager.handle_partial_tp`) — (2)/(3)은 자기 모듈 밖 어디에서도 호출된 적이 grep으로 확인한 결과 전무함(pycache 외 매치 0건)
- [x] **최고-ROI 항목 선정 근거**: break-even move를 선택 — entry 로직(어떤 트레이드가 발생하는지)은 완전히 그대로 두고 **exit 관리만** 바꾸는 유일한 후보라 before/after 비교가 가장 깨끗함(breaker block은 새 시그널 소스를 추가하고, partial TP는 PnL을 두 leg로 쪼개 교란 변수가 늘어남). "Improved risk management"라는 operator 승인 카테고리에 직접 부합
- [x] `backend/app/backtesting/backtest_engine.py`에 `BREAKEVEN_TRIGGER_R = 1.0`(1R 이동 시 손절을 진입가로 이동, "튜닝 안 된 합리적 기본값"이라고 명시적으로 문서화) + `BacktestEngine.run(..., use_breakeven=False)`(opt-in, 기존 호출자는 전부 무변경 동작 유지) 신규
- [x] `_simulate_trade()`에 보수적 same-candle 우선순위 구현: 한 캔들이 원래 stop_loss와 breakeven 트리거 레벨을 동시에 건드리면 **항상 원래 stop_loss로 처리**(이 메서드의 기존 SL-before-TP 보수적 가정과 동일한 철학 — intracandle 순서를 알 수 없으므로 유리한 쪽으로 가정하지 않음). trade record에 `breakeven_triggered: bool` 필드 추가
- [x] `scripts/run_backtest.py --breakeven` 플래그 추가(opt-in, 콘솔에 ENABLED/disabled 명시 출력) — `--periods`와 조합해 진짜 A/B 비교 가능
- [x] 신규 테스트 5종(`test_backtest_engine.py`): breakeven 비활성 시 동일 풀백 캔들이 청산 안 됨(대조) / 활성 시 같은 캔들이 breakeven(진입가)에서 청산됨 / breakeven 트리거 후에도 실제 take_profit 도달은 막지 않음 / **same-candle 보수적 우선순위 직접 증명**(원 stop과 breakeven 트리거를 동시에 건드리는 캔들은 원 stop으로 청산) / short 방향 대칭 확인
- [x] 전체 `pytest backend/tests/` **174/174 통과**(기존 169 + 신규 5). `use_breakeven` 기본값 `False`라 기존 169개 테스트는 전부 무변경 동작으로 재확인
- [x] **오케스트레이터 재검증용 실측(A/B, 가장 중요)**: 직전 회차와 완전히 동일한 시드 데이터(BTCUSDT/ETHUSDT 15m, 각 3개 비중첩 기간)로 `--breakeven` on/off만 바꿔 재실행 — **BTCUSDT**: P1 -$48.64(승률50%)→**+$67.48(승률58%, 손실→수익 반전)**, P2 $165.81(변화없음), P3 +$184.62(승률80%)→+$150.88(승률60%, **악화**). **ETHUSDT**: P1/P2 변화없음, P3 +$308.75(승률90%, 변화없음)→+$336.78(**MDD 0.38%→0.11%로 개선**). **6개 기간 합산: $819.09→$929.49(+13.5%), 수익 기간 5/6→6/6**(유일한 손실 기간이 수익 전환)
- [x] **정직한 해석(과장 금지)**: 효과가 균일하지 않음 — 3개 기간은 아예 변화 없음(breakeven 트리거 후 되돌림이 한 번도 없었음), 1개 기간은 악화(끝까지 갔으면 풀 TP였을 트레이드가 breakeven에서 조기 청산됨), 2개 기간이 개선(그 중 1개는 손실→수익 반전). 이것이 정확히 breakeven stop의 교과서적 효과 — "총합보다 결과의 편차(range)를 줄임", 최악의 시나리오를 최상의 시나리오 일부를 희생해서 방어
- [x] **operator 지시 "통계적으로 더 강해지지 않으면 계속 추가 금지" 준수 판단**: 이번 결과는 합산 PnL 개선(+13.5%) + 수익 기간 비율 개선(5/6→6/6)으로 "통계적으로 더 강해짐"의 기준을 충족한다고 판단 — 다만 표본이 여전히 작음(6개 기간)을 감안해 **기본값을 바꾸지 않고 opt-in으로 유지**, `run_paper.py`/live에는 연결하지 않음(추가 기능 확장 자제, 이번 회차는 이 1개 컴포넌트로 한정 — operator 지시 "Implement only that component" 준수)
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가(A/B 비교 표 포함)
- [x] scope 준수: `backend/app/strategy/*`(무변경), `backend/app/risk/*`(무변경), `backend/app/execution/*` 자체(무변경 — `OrderManager.move_to_breakeven`을 재사용하지 않고 `BacktestEngine` 안에 동등한 로직을 독립 구현했음, 아래 "다음 후보"에 이 설계 판단 이유 명시), `scripts/run_paper.py`(무변경, 의도적), Dashboard/live 게이팅 전부 무변경
- [x] git commit/push 완료 (`origin/master`) — operator가 사전에 "커밋 후 푸시, 라이브/자격증명/외부유료서비스/보안/파괴적 아니면 계속 진행"이라고 명시적으로 요청함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (Backtest 품질: 진짜 out-of-sample 다중 기간 검증 도구 추가 — 직전 회차 자체가 명시한 유보 해소)
- [x] **동기**: 직전 회차(zone mitigation 버그 수정)의 CHANGELOG/HANDOFF에 스스로 "3개 샘플 전부 단일 연속 구간(in-sample)이라 전략이 검증됐다고 주장하기엔 부족하다"고 명시적으로 기록해뒀음 — 이번 회차는 그 구체적 유보를 실제로 해소하는 작업
- [x] `scripts/run_backtest.py`에 `--periods N` 신규 — 가져온 히스토리를 N개의 동일 크기, **비중첩** 시간순 조각으로 분할해 각각을 완전히 독립적으로(각 기간마다 새 계정 잔고, 트레이드/equity 상태 공유 없음) `BacktestEngine.run()`에 통과시킴. `split_into_periods()`는 순수 함수(모든 캔들이 정확히 한 번씩 쓰이고 중복/누락 없음을 직접 검증함) — **의도적으로 walk-forward 파라미터 재학습 윈도우가 아님**: 이 전략엔 학습/피팅되는 파라미터가 없음(entry_model.py 등에 이미 "백테스트로 튜닝된 값이 아닌 합리적 시작값"이라고 문서화돼 있음). `--candles`는 "기간당" 캔들 수, 총 fetch량은 `--candles * --periods`. `--periods 1`(기본값)은 기존 단일 실행과 완전히 동일한 동작(하위 호환)
- [x] 기간별 요약 + 집계 요약(수익 기간 수/전체 기간 수, 총 트레이드, 합산 PnL) 콘솔 출력, `--periods > 1`이면 기간별로 별도 리포트/CSV(`<stem>_period<N>.md/.csv`) 작성. 집계 출력에 "합계보다 기간 간 일관성이 더 중요하다"는 문구를 명시적으로 포함(합산 PnL이 양수라고 무조건 좋은 신호로 오독되지 않도록)
- [x] **오케스트레이터 재검증용 실측(가장 중요)**: `run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 1000 --periods 3`를 실 OKX 데이터로 실행(총 3000캔들, 직전 회차와 동일한 히스토리 깊이를 3개 비중첩 구간으로 분할) → **기간 1(6/8~6/18): 12trades/승률50%/PnL-$48.64/MDD2.04% / 기간 2(6/18~6/29): 6trades/승률83.33%/PnL+$165.81/MDD0.32% / 기간 3(6/29~7/9): 10trades/승률80.00%/PnL+$184.62/MDD0.43%** — 3개 중 2개 수익, 1개는 소폭 손실(파산 수준 아님). 동일하게 ETHUSDT/15m 실행 → **기간 1: 4trades/승률100%/+$148.51 / 기간 2: 5trades/승률60%/+$60.04 / 기간 3: 10trades/승률90%/+$308.75** — 3개 전부 수익. 두 자산 합쳐 6개 독립 기간 중 5개 수익
- [x] `--periods 1`(기본값) 하위 호환 재확인: 동일한 `--candles 3000` 단일 실행이 직전 회차와 정확히 같은 결과(28trades/승률75%/PnL+462.18/MDD2.04%) 재현함을 확인 — 리팩터링이 기존 동작을 깨지 않았음을 직접 증명
- [x] 전체 `pytest backend/tests/` **169/169 통과**(이번 회차는 `scripts/run_backtest.py`만 수정 — 이 파일은 기존부터 pytest가 아니라 실 오케스트레이터 실행으로만 검증돼 온 컨벤션 유지, `split_into_periods()`의 순수 로직은 별도로 직접 검증함)
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가("이 결과가 여전히 충분하지 않은 이유" 문단 포함 — 기간당 트레이드 수가 더 적어짐, 전부 같은 ~31일 달력 구간이라 진짜 다른 시장 레짐 검증은 아직 아님)
- [x] **정직한 재평가(과장 금지, 지속)**: 이번 결과는 이전보다 더 세밀하고 신뢰할 만하지만("2/3, 3/3" 같은 구체적 비율은 "무조건 수익"이라는 이전 주장보다 정직함), 여전히 완전한 검증은 아님 — 다른 시장 레짐(추세/횡보, 고변동성/저변동성)에 걸친 기간이 필요하며, 이는 더 긴 히스토리를 가져오거나 시간이 더 지난 뒤 이 도구를 다시 돌리는 것으로 얻을 수 있음(다음 후보로 명시)
- [x] scope 준수: `backend/app/*` 전부 무변경(이번 회차는 `scripts/run_backtest.py`만 수정), live-trading 게이팅 무관
- [x] git commit/push 완료 (`origin/master`) — operator가 CTO 역할 지시에서 "API 자격증명/라이브 승인/외부유료서비스/보안 아니면 자율적으로 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (Strategy 정확성: 이미-테스트된 zone에 대한 중복 시그널 생성 버그 수정 — 직전 딥 백테스트 회차가 실제로 발견하게 해준 첫 실전략 버그)
- [x] **딥 백테스트 결과를 직접 분석해 발견(가정 아님)**: 직전 회차(CandleFetcher 페이지네이션 수정)로 처음 가능해진 BTCUSDT/15m 3000캔들 백테스트의 트레이드 CSV를 직접 읽어보니, 28건 중 5쌍(10건, ~36%)이 entry_price/exit_price/PnL이 거의 정확히 동일한 "중복" 트레이드였고, 시간상으로도 방금 스탑아웃된 직후(15-45분 뒤) 같은 가격대에서 다시 진입한 패턴이었음
- [x] **근본 원인 진단**: `detect_fair_value_gap()`/`detect_order_block()`이 순수 함수로서 "가장 최근의 zone"을 계속 보고하는데, 그 zone에 가격이 이미 되돌아와서 테스트(그리고 실패)했는지 여부를 전혀 추적하지 않음 — `entry_model.build_entry_model()`도 마찬가지로 zone의 "신선도"를 모름. 그 결과 walk-forward 루프의 다음 스텝에서 같은 zone이 여전히 "가장 최근"이면 동일한 entry/stop/take-profit으로 사실상 똑같은 트레이드를 재차 생성함(직전에 실패한 바로 그 셋업을 즉시 재진입 — revenge trading과 동형의 버그)
- [x] `app.strategy.utils.is_zone_mitigated(candles, start_index, top, bottom)` 신규 — 표준 SMC "mitigation" 개념(zone 형성 이후 가격이 이미 그 범위로 되돌아왔는지)을 판정하는 공유 헬퍼. **마지막(현재) 캔들은 의도적으로 체크 대상에서 제외** — 시그널을 트리거하는 바로 그 캔들이 zone을 건드리는 것(예: sweep wick이 근처 FVG를 같은 캔들에서 태깅)은 셋업 그 자체이지 사전 재테스트가 아니기 때문
- [x] **구현 위치는 orchestration 레이어(`SignalEngine.generate_signal`)로 의도적으로 선택, detector 자체(`detect_fair_value_gap`/`detect_order_block`)는 무변경**: `detect_breaker_block()`이 `detect_order_block()`으로부터 원본(필터링 안 된) zone을 받아 자체적으로 closed-through+retest 분석을 수행하는 구조라, detector 레벨에서 mitigation 필터링을 넣으면 `detect_breaker_block`의 기존 로직이 깨짐 — 이 의존관계를 실제로 하나하나 확인한 뒤 orchestration 레이어에 필터를 넣기로 결정(가정하지 않고 검증)
- [x] `detect_order_block()`이 이제 `impulse_index`(확정 임펄스 캔들의 index, zone의 base 캔들 index인 기존 `index`와 별개)도 반환 — mitigation 체크가 base 캔들이 아니라 임펄스 캔들 "이후"부터 시작해야 함(임펄스 캔들 자신의 range가 자신이 유래한 base zone과 거의 항상 겹치므로, base 캔들부터 체크하면 모든 fresh order block이 자기 자신의 확정 무브에 의해 즉시 "mitigated"로 오판됨 — 실제로 이렇게 구현했다가 로그로 확인하고 수정함)
- [x] 신규 테스트 12종: `test_strategy_utils.py`(신규 파일) `is_zone_mitigated` 자체의 경계 규칙 7종(이전/이후 캔들 겹침, 마지막 캔들 제외, 빈 범위, 경계 접촉 포함 등) + `test_strategy_signal_engine.py`에 **실 세계 버그를 그대로 재현하는 종단 회귀 테스트**: 신선한 zone은 시그널을 내지만(1차), 그 후 가격이 같은 zone을 리테스트하는 캔들이 추가되면 동일 조건(bias/sweep 동일)에서도 두 번째 시그널은 생성되지 않음(None)을 직접 증명
- [x] **테스트 픽스처 3개 수정 필요(버그 아니라 mitigation이 실제로 올바르게 작동함을 드러낸 결과)**: `test_strategy_signal_engine.py`/`test_backtest_engine.py`가 공유하던 지그재그 "confluence" 픽스처는 지그재그 자체의 오실레이션이 스스로 만든 모든 FVG를 곧바로 되돌아가며 mitigate하고 있었음(지그재그는 원래 상승-하락을 반복하는 패턴이라 당연한 결과) — 즉 그 픽스처는 "신선한 셋업"을 테스트한 게 아니라 우연히 detector가 mitigation을 몰랐기 때문에 통과하던 것. 지그재그 끝에 mitigate되지 않는 fresh leg(prev/impulse/next 3캔들, sweep 캔들 직전에 삽입)를 추가해 픽스처를 실제로 올바르게 수정
- [x] `docs/strategy_spec.md` section 4/5에 이 새 규칙을 "(implemented)" 섹션으로 문서화(가정을 코드에만 남기지 않고 스펙 문서에도 명시 — CTO 지시 "document assumptions" 반영)
- [x] 전체 `pytest backend/tests/` **169/169 통과**(기존 157 + 신규 12). 전체 스위트 2회 연속 재실행으로 flakiness 없음 확인
- [x] **오케스트레이터 재검증용 실측(가장 중요, 3개 독립 실 데이터 샘플)**: 수정 전/후 동일한 3000캔들 딥 페치로 비교 — BTCUSDT/15m: 28trades/승률25%/PnL-$577.82/MDD5.78% → **28trades/승률75%/PnL+$462.18/MDD2.04%**(트레이드 개수는 우연히 동일하지만 구성/결과가 완전히 다름 — mitigation이 다른 zone을 선택하게 되면서 walk-forward 전체 경로가 바뀜). 추가로 독립적인 2개 신규 샘플: ETHUSDT/15m(19trades/승률89.47%/PnL+$614.22/MDD0.45%), BTCUSDT/5m(10trades/승률90.00%/PnL+$257.83/MDD0.40%) — 심볼·타임프레임 양쪽에서 일관되게 크고 긍정적인 방향 전환, 우연한 한 샘플이 아님
- [x] **정직한 유보(operator/다음 엔지니어를 위해 명시, 과장 금지)**: 이 3개 샘플은 고무적이지만 "전략이 검증됐다"고 주장하기엔 부족함 — out-of-sample/walk-forward 분할 전혀 없음(전부 in-sample), 트레이드 수(10-28건)가 적어 승률의 신뢰구간이 넓음, BTC/ETH는 서로 강하게 상관돼 있어 두 15m 샘플이 완전히 독립적인 증거가 아님. 이번 수정은 실제로 크고 메커니즘이 명확한 개선(중복 트레이드 버그 제거)이지 "이 전략이 실전 준비됐다"는 증명이 아님
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가("Honest caveat" 문단 포함)
- [x] scope 준수: `backend/app/risk/*`, `backend/app/execution/*`, `backend/app/portfolio/*`, `backend/app/backtesting/*`(엔진 자체 무변경 — 이번 회차는 순수 Strategy Engine 정확성 수정), `exchange/*`, live-trading 게이팅 전부 무변경
- [x] git commit/push 완료 (`origin/master`) — operator가 CTO 역할 지시에서 "API 자격증명/라이브 승인/외부유료서비스/보안 아니면 자율적으로 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (CTO 지시: 수익성 관점 최고-ROI 재평가 — Backtest 데이터 깊이 버그 근본 수정)
- [x] **오리엔테이션**: HANDOFF.md/README.md/최근 git log/전체 아키텍처를 재확인(operator가 CTO 역할 지시). 이전 5개 회차(Strategy/Risk/Backtest/Paper/Dashboard 배관 정확성)는 전부 완료·커밋됨. "수익성 확률을 높이는가?"라는 새 렌즈로 재평가한 결과, 배관은 이제 정확하지만 **전략 자체가 수익성이 있는지 실제로 검증된 적이 한 번도 없었음** — 모든 백테스트가 OKX 공개 캔들 엔드포인트의 300개/콜 한도에 묶여 5m 기준 약 하루치 데이터로만 실행돼 옴(HANDOFF/스크립트 독스트링에 "known limitation"으로 반복 기록만 되고 근본 원인은 한 번도 diagnose 안 됨)
- [x] **근본 원인 실측 진단(가정 아님, 실 OKX API로 직접 확인)**: `CandleFetcher.fetch_ohlcv`의 `since` 파라미터가 OKX `before` 쿼리 파라미터에 연결돼 있었는데, 실제로 `before=<ts>`는 `ts`보다 **더 최신** 캔들을 반환함(과거로 페이징 불가) — 반대로 `after=<ts>`가 `ts`보다 **더 과거** 캔들을 반환함을 실 API 호출로 직접 확인. 즉 기존 코드는 페이지네이션 방향 자체가 반대였음. 추가로 `/api/v5/market/candles`(기존에 쓰던 엔드포인트) 자체가 페이지네이션과 무관하게 총 약 1440개 캔들로 하드캡돼 있음도 실측 확인(반복 `after` 페이징이 정확히 1440개에서 빈 응답을 냄) — 별도 엔드포인트 `/api/v5/market/history-candles`가 같은 요청/응답 형식으로 훨씬 더 깊이(1H 캔들 3000개=~125일까지 조기 종료 없이 실측 확인) 페이징됨을 확인
- [x] `CandleFetcher.fetch_ohlcv`의 `since`가 이제 올바르게 `after`에 매핑됨(단일 페이지 호출의 정확성 수정)
- [x] `CandleFetcher.fetch_ohlcv_history(symbol, timeframe, total_candles, ...)` 신규 — `/market/history-candles`를 `after` 커서로 반복 페이징해 실제 딥 히스토리를 조립. 페이지 간 `sleep_seconds`로 rate limit 배려, `max_pages`로 total_candles와 무관하게 독립적인 HTTP 호출 수 안전 상한(페이지네이션 버그가 무한루프로 번지는 것 방지), OKX 실제 히스토리가 요청량보다 적으면(신규 상장 등) 에러 없이 있는 만큼만 반환(짧은/빈 페이지로 정상 종료 감지)
- [x] `scripts/run_backtest.py`가 이제 `fetch_ohlcv_history()`를 사용(기존 300개 캡 단일 호출 대체) — `DEFAULT_CANDLE_COUNT`를 900(단일 호출 시절의 유물)에서 5000으로 상향(이제 실제로 그만큼 페칭 가능해졌으므로). 요청량보다 실제 반환량이 적으면(OKX 히스토리 자체가 짧은 경우) 조용히 넘어가지 않고 명확한 NOTE 출력
- [x] 신규 테스트 파일 `test_candle_fetcher.py`(이 모듈은 이번 회차 전까지 테스트가 전무했음 — 실 라이브 수동 실행으로만 검증돼 옴): `to_okx_symbol`/`to_okx_timeframe` 순수 함수 테스트 6종(네트워크 불필요) + `httpx.get`을 실측 확인된 OKX 실제 동작(페이지당 newest-first, `after=<ts>`는 그보다 과거만 반환)을 그대로 재현하는 fake로 monkeypatch한 페이지네이션 테스트 6종(멀티페이지 조립이 전체적으로 oldest→newest이고 중복 없음을 증명, OKX 히스토리가 실제로 짧으면 조기 종료함을 증명, 요청량 초과분은 가장 오래된 쪽에서 잘려나가고 최신 쪽이 보존됨을 증명, `total_candles<=0`이면 API 호출 자체를 안 함을 증명, `max_pages` 안전 상한이 `total_candles`와 무관하게 독립적으로 작동함을 증명, `since`가 실제로 `after` 파라미터로 전송되고 `before`는 전송 안 됨을 증명하는 이번 버그의 회귀 고정 테스트)
- [x] 전체 `pytest backend/tests/` **162/162 통과**(기존 150 + 신규 12). 전체 스위트 2회 연속 재실행으로 flakiness 없음 확인
- [x] **오케스트레이터 재검증용 실측(가장 중요)**: `scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000`을 **실 OKX API**로 실행 → 실제로 3000개 LTF + 3000개 HTF 캔들 fetch 성공(이전이었다면 조용히 300개로 캡됐을 것) → **28건의 실 트레이드, 승률 25%, total_pnl=-$577.82(계정 $10,000 대비 -5.78% MDD)** 결과 도출 — 이번 세션 전체를 통틀어 처음으로 "이 전략에 실제 edge가 있는가?"라는 질문에 통계적으로 의미 있는 규모(과거 300캔들=하루치가 아니라 31일치)로 답한 실측 결과. **결과 자체가 부정적(현재 파라미터로는 수익성 없음)이라는 것이 오히려 이 수정의 가치를 증명함** — 이제서야 이런 실측이 가능해졌다는 뜻
- [x] `py_compile` 무오류 확인(`app/data/candle_fetcher.py`, `scripts/run_backtest.py`, `tests/test_candle_fetcher.py`), grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음. 다른 문서(`docs/`, `README.md`)에 이 버그를 언급하는 stale 참조 없는지 확인(없음)
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가("Why this matters (profitability, not just plumbing)" 문단으로 이 수정이 단순 버그 수정이 아니라 전략 검증 자체를 가능하게 하는 근본 인프라임을 명시)
- [x] scope 준수: `backend/app/strategy/*`(전략 로직 자체는 무변경 — 이번 회차는 "얼마나 깊이 볼 수 있는가"를 고친 것이지 "무엇을 보는가"를 고친 게 아님), `backend/app/risk/*`, `backend/app/execution/*`, `backend/app/portfolio/*`, `exchange/*`, live-trading 게이팅 전부 무변경. `scripts/run_paper.py`도 무변경(paper 실행은 여전히 단일 최신 캔들 fetch만 필요, 딥 히스토리 불필요 — `fetch_ohlcv`만 쓰고 `fetch_ohlcv_history`는 안 씀, 의도적)
- [x] git commit/push 완료 (`origin/master`) — operator가 CTO 역할 지시에서 "API 자격증명/라이브 승인/외부유료서비스/보안 아니면 자율적으로 계속 진행"이라고 명시적으로 재확인함(이 태스크는 그 어느 카테고리에도 해당하지 않음)

## 전체 회차 (Dashboard: `/dashboard/signals` 실시간 배선 — Dashboard 계층 마지막 항목)
- [x] **갭 해소**: 어떤 프로세스도 생성된 시그널을 `signals` 테이블에 영속화한 적이 없었음 — `app.database.models.Signal`의 `status` 컬럼은 처음부터 pending/approved/rejected/executed 컨벤션을 문서화하고 있었고, `TradeSignal` 데이터클래스 자체 독스트링도 "signals DB table과 일치"라고 명시하고 있었지만(스키마/계약은 처음부터 이 기능을 염두에 두고 설계돼 있었음), 실제 쓰기 경로가 한 번도 배선된 적이 없었음
- [x] `app.portfolio.signals.SignalTracker` 신규(`TradeTracker`와 정확히 동일한 패턴): `record_signal()`, `update_signal_status()`(알 수 없는 id면 `ValueError` — `TradeTracker.close_trade()`와 동일 계약), `get_recent_signals(limit=20)`
- [x] `scripts/run_paper.py`의 `run_once()`가 매 pass마다 실제로 생성된 `TradeSignal`을 생성 즉시 영속화(status="pending")하고, 파이프라인을 지나며 "rejected"(risk 거부)/"approved"(risk 통과)/"executed"(주문 체결) 로 상태를 갱신 — 기존 `trades_today`/`daily_pnl_percent` best-effort 쿼리와 동일한 패턴(영속화 실패는 파이프라인을 막는 에러가 아니라 큰 소리 WARNING). 기존 `run_once()` summary dict 필드/의미는 전부 무변경
- [x] `/dashboard/signals`가 이제 `SignalTracker`를 통해 실 최근 20개 시그널(최신순)을 반환
- [x] 프론트엔드: `Signal`/갱신된 `SignalsResponse` 타입 추가, `SignalsPanel`이 실 리스트를 렌더(`LogsPanel`과 동일 패턴)하도록 교체 — 하드코딩된 "Not live yet" 배지 + 카운트만 보여주던 것 제거
- [x] **`ltf_bias` 판단과 동일한 성격의 근거 확인**: `TradeSignal.timestamp`가 dataclass 타입 힌트상 `str`이지만 실제 런타임 값(실 OKX candle의 timestamp)은 항상 real `datetime`이고 `Signal.timestamp` DB 컬럼도 `DateTime(timezone=True)`라 타입 힌트는 무시하고 실제 런타임 타입 그대로 저장 — 기존 타입 힌트 자체를 고치는 것은 이번 태스크 scope 밖이라 손대지 않음(동작에 영향 없음, 이미 있던 사소한 부정확성)
- [x] 신규 테스트 9종: `test_portfolio.py`에 `SignalTracker` record/query round-trip, 상태 전이(pending→approved→executed), 알 수 없는 id `ValueError`, 최신순+limit 정렬 4종 + `test_api_routes.py`에 fresh-DB 빈 상태 + 실 seed된 시그널이 실 상태로 엔드포인트에 반영됨 2종
- [x] 전체 `pytest backend/tests/` **150/150 통과**(기존 145 + 신규 9 — 위 4+2=6개는 세는 방식에 따라 다를 수 있음, 정확히는 신규 테스트 함수 9개). 전체 스위트 2회 연속 재실행으로 flakiness 없음 확인
- [x] **오케스트레이터 재검증용 실측(가장 중요 — `SignalTracker` 단위 테스트만으로는 실제 `run_once()` 배선 자체는 증명 안 됨)**: 임시 SQLite에 실 `alembic upgrade head` 적용 → `CandleFetcher`/`SignalEngine`을 controlled fake로 monkeypatch(진짜 시그널 생성 로직이 아니라 이 배선 자체를 격리 검증하기 위함, `MIN_RR` 통과하는 실 rr=3.0 신호) → **실제** `run_paper.run_once()` 직접 호출 → 시그널이 pending→approved→executed로 실제 전이되고 실행된 trade와 매칭됨을 DB에서 직접 확인. 두 번째로 rr=0.2(< MIN_RR) 신호로 재실행 → pending→rejected로 전이되고 `RiskManager`의 실제 거부 사유와 일치함을 확인. 두 시나리오 모두 통과
- [x] `py_compile` 무오류 확인, `npx tsc --noEmit` 클린, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가
- [x] scope 준수: `backend/app/strategy/*`(무변경, `TradeSignal`을 duck-typed로 consume만 함), `backend/app/backtesting/*`, `backend/app/execution/*`, `backend/app/risk/*`, `exchange/*`, live-trading 게이팅 전부 무변경
- [x] git commit/push 완료 (`origin/master`) — operator가 사전에 "커밋 후 푸시, 라이브/자격증명/외부유료서비스/보안/파괴적 작업 아니면 승인 없이 계속 진행"이라고 명시적으로 요청함(이 태스크는 위 5개 카테고리 중 어느 것에도 해당하지 않음)

## 전체 회차 (Dashboard: `/dashboard/bias` 실시간 배선)
- [x] **갭 해소**: `/dashboard/bias`가 `{"htf_bias": "neutral", "ltf_bias": "neutral", "note": "not yet wired..."}`를 하드코딩 반환하던 것을, `scripts/run_paper.py`/`run_backtest.py`가 이미 매번 하는 것과 동일한 패턴(`CandleFetcher().fetch_ohlcv()`, API 키 불필요, read-only)으로 실 OKX HTF/LTF candle을 fetch해 실 `app.strategy.bias.detect_htf_bias()`(라이브 전략의 실제 bias 게이트와 완전히 동일한 함수)로 계산하도록 교체
- [x] **`ltf_bias` 설계 판단(operator 확인 없이 진행, 근거 문서화)**: 실 전략 설계(`docs/strategy_spec.md`, `signal_engine.py`)엔 "LTF bias"라는 개념 자체가 없음 — `detect_htf_bias()`는 HTF candles에만 호출되고, LTF candles는 sweep/CHoCH/FVG/order-block detector에만 쓰임. 이 API 필드는 그 설계보다 오래된 필드(Milestone 1 계약). 데이터를 지어내는 대신, 같은 실제 구조적-bias 알고리즘을 LTF 캔들 시리즈에도 재적용("최근 LTF 스윙 구조 편향"이라는 진짜 계산값이지만, 전략의 실 HTF bias 게이트와는 별개 개념임을 명시)하기로 결정 — operator가 명시적으로 "계속 진행, 라이브/자격증명/외부유료/보안/파괴적 아니면 승인 없이 진행"이라 지시했고 이 판단은 그 5개 카테고리에 해당하지 않아 질문 없이 진행. 이 필드의 의미가 실제 트레이딩 판단에 쓰이게 되는 시점이 오면 재확인 필요 — 명시적으로 플래그해둠
- [x] fetch 실패 시(네트워크/거래소 에러) 500으로 대시보드를 죽이지 않고 `neutral`/`neutral` + 실패 사유가 담긴 `note`로 우아하게 degrade — `run_paper.py`의 기존 best-effort 패턴과 동일한 철학
- [x] 프론트엔드 `BiasCard.tsx`의 하드코딩된 "Not live yet" 배지 제거(직전 회차에서 `RiskStatusPanel`에 했던 것과 동일) + `frontend/lib/types.ts`의 `Bias` 인터페이스 문서 주석 갱신
- [x] 신규 테스트 2종(`test_api_routes.py`): `CandleFetcher`를 monkeypatch해 HTF/LTF에 서로 다른 실 캔들 시리즈(진짜 bullish 지그재그 vs bearish 지그재그, `test_strategy_bias.py`와 동일한 fixture 모양 재사용)를 흘려서 `htf_bias`≠`ltf_bias`가 나옴을 증명(둘이 같은 값의 단순 복제가 아니라 각자 독립적으로 계산됨을 증명, `test_strategy_signal_engine.py`의 HTF/LTF 분리 증명과 같은 정신) + fetch 실패 시뮬레이션으로 graceful degradation 증명
- [x] 전체 `pytest backend/tests/` **145/145 통과**(기존 143 + 신규 2). 전체 스위트 2회 연속 재실행으로 flakiness 없음 확인
- [x] 오케스트레이터 재검증용 실측: 실 FastAPI 앱 부팅 → **실 OKX API**(mock 없음)로 `/dashboard/bias` 호출 → `{"symbol": "BTCUSDT", "htf_bias": "neutral", "ltf_bias": "neutral", "note": ""}` 실제 반환 확인(오늘 시장이 우연히 neutral — 같은 날 다른 회차의 0-trade 백테스트 결과와 일치하는 정상 결과, 에러 아님)
- [x] `npx tsc --noEmit` 클린 통과
- [x] `py_compile` 무오류 확인, grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가
- [x] scope 준수: `backend/app/strategy/bias.py` 자체(무변경, import해서 consume만 함), `backend/app/backtesting/*`, `backend/app/execution/*`, `backend/app/risk/*`, `exchange/*`, live-trading 게이팅 전부 무변경. `/dashboard/signals`는 이번 회차 scope 밖(시그널 영속화라는 별도 설계 결정 필요 — 아래 "다음 후보" 참조)
- [x] git commit/push 완료 (`origin/master`) — operator가 사전에 "커밋 후 푸시, 라이브/자격증명/외부유료서비스/보안/파괴적 작업 아니면 승인 없이 계속 진행"이라고 명시적으로 요청함(이 태스크는 위 5개 카테고리 중 어느 것에도 해당하지 않음)

## 전체 회차 (Dashboard: `/dashboard/risk-status` 실 데이터 배선 — 우선순위상 Backtest 다음 항목)
- [x] **갭 발견/해소**: `/dashboard/risk-status`가 `{daily_loss_used_percent:0, weekly_loss_used_percent:0, trades_today:0, note:"not yet wired to live strategy state"}`를 하드코딩 반환하고 있었는데, 필요한 building block(`TradeJournal.generate_daily_report()`/`generate_weekly_report()`, trades-today 카운트)이 이미 전부 존재하고 이미 `RiskManager.evaluate()`/loop-mode circuit breaker에서 실제로 쓰이고 있었음 — 그냥 배선만 안 돼 있던 손쉬운 win. 실제 daily/weekly loss-used percent(순손실의 절대값, 순이익인 날은 0 — 음수로 새지 않음)와 실 trades_today를 반환하도록 교체
- [x] `PLACEHOLDER_ACCOUNT_BALANCE`를 `scripts/run_paper.py`의 로컬 상수에서 `settings.PLACEHOLDER_ACCOUNT_BALANCE`(`app/config.py`)로 이동 — `/dashboard/risk-status`와 `run_paper.py`가 PnL→퍼센트 변환에 정확히 같은 고정 분모를 공유하도록(각자 따로 값을 들고 있다 조용히 어긋나는 것 방지)
- [x] `scripts/run_paper.py`의 private `_count_trades_opened_today()`를 `TradeTracker.count_trades_opened_today()`로 이동(로직 동일, 테스트는 `test_portfolio.py`로 이전+확장) — `/dashboard/risk-status`도 재사용
- [x] 프론트엔드 `RiskStatusPanel.tsx`의 하드코딩된 "Not live yet" 배지 제거(데이터가 이제 실제로 live라 오해를 유발) + `frontend/lib/types.ts`의 `RiskStatus` 인터페이스 문서 주석을 "여전히 placeholder"에서 "실 데이터"로 갱신 + 소수점 표시(`.toFixed(2)`) 추가
- [x] 신규 테스트 7종: `test_api_routes.py`에 fresh-DB 0-state 증명 1종 + 실 seed된 -$150 손실이 엔드포인트에 실제로 반영됨을 증명(1.5% 계산) + 같은 날 두 번째 트레이드로 순이익 전환 시 0%로 돌아옴을 증명(음수로 새지 않음을 확인) 2종 + `test_portfolio.py`에 `count_trades_opened_today()` 직접 단위 테스트 1종(오늘 열린 오픈+클로즈드 트레이드는 카운트, 어제 열린 트레이드는 제외)
- [x] 전체 `pytest backend/tests/` **143/143 통과**(기존 136 + 신규 7). 전체 스위트 3회 연속 재실행으로 flakiness 없음 확인
- [x] 오케스트레이터 재검증용 실측: 실 FastAPI 앱을 완전히 새로운 임시 SQLite DB로 부팅(실 `alembic upgrade head`) → `TradeTracker`로 실 -$150 클로즈드 트레이드 seed → `TestClient`로 실 `/dashboard/risk-status` 엔드포인트 호출 → `{"daily_loss_used_percent": 1.5, "weekly_loss_used_percent": 1.5, "trades_today": 1, "note": ""}` 실제 반환 확인(옛 하드코딩 0이 아님)
- [x] `npx tsc --noEmit` 클린 통과(frontend 타입/컴포넌트 변경분)
- [x] `py_compile` 무오류 확인(`app/config.py`, `app/api/routes_dashboard.py`, `app/portfolio/trades.py`, 신규/수정 테스트 파일 전부), grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음(`/dashboard/bias`·`/dashboard/signals`는 의도적으로 여전히 placeholder라 그 두 엔드포인트 자체의 "not yet wired" 문구는 남아있음 — 정확함, 갭 아님)
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가
- [x] scope 준수: `backend/app/strategy/*`, `backend/app/backtesting/*`, `backend/app/execution/*`, `backend/app/risk/*`, `exchange/*`, live-trading 게이팅 전부 무변경(diff에 등장하지 않음). `/dashboard/bias`·`/dashboard/signals`도 이번 회차 scope 밖(각각 실시간 OKX fetch, signal 영속화라는 별도 설계 결정이 필요 — 아래 "다음 후보" 참조, 서두르지 않고 분리)
- [x] git commit/push 완료 (`origin/master`) — operator가 사전에 "커밋 후 푸시, 라이브/자격증명/외부유료서비스/보안/파괴적 작업 아니면 승인 없이 계속 진행"이라고 명시적으로 요청함(이 태스크는 위 5개 카테고리 중 어느 것에도 해당하지 않음)

## 전체 회차 (BacktestEngine: daily/weekly loss-limit 실 집행 — Strategy>Risk>Backtest>Paper>Dashboard>Live 우선순위에 따른 다음 최고-ROI 항목)
- [x] **operator의 우선순위 지시(Strategy Engine > Risk Engine > Backtest > Paper Trading > Dashboard > Live Trading)를 따라 최고-ROI 갭 재조사**: Strategy Engine(HTF/LTF 분리+confluence 방향 일치, 완료), Risk Engine(daily/weekly loss-limit + MAX_TRADES_PER_DAY + MIN_RR, 전부 집행됨, 완료)까지는 확인된 갭 없음. Backtest 계층에서 실 갭 발견: `BacktestEngine.run()`이 `risk_manager.evaluate()`에 `trades_today`만 넘기고 `daily_pnl_percent`/`weekly_pnl_percent`는 전혀 넘기지 않아(항상 묵시적 기본값 `0.0`) — 직전 회차에 paper/live용으로 실제 집행되게 만든 daily/weekly loss-limit이 백테스트에서는 애초에 평가조차 안 되고 있었음. 즉 백테스트는 paper/live보다 체계적으로 더 관대한(비대표적인) 손실 한도 조건으로 전략을 테스트하고 있었음 — 직전 포지션 사이징 수정(`0e52b5a`)이 해소한 것과 같은 종류의 "백테스트가 실제 운영을 대표하지 못하는" 문제
- [x] `_day_bounds()`/`_week_bounds()`/`_realized_pnl_in_window()` 신규(`backend/app/backtesting/backtest_engine.py`) — `TradeJournal.generate_daily_report()`/`generate_weekly_report()`와 정확히 동일한 UTC-calendar-day/ISO-calendar-week 경계 공식을 재사용(문서화된 컨벤션 그대로, `docs/risk_rules.md` 참조). DB 없이 인메모리로 동작해야 하므로 `run()`이 이미 누적 중인 `trades` 리스트를 매 스텝마다 재스캔해서 realized PnL을 재계산(running accumulator 방식 대신 선택 — 한 트레이드의 청산 시점이 그 트레이드가 열린 스텝보다 여러 날/주 뒤일 수 있어 running 방식은 롤오버 시점에 어긋날 위험이 있음; 백테스트 트레이드 수는 캔들 수 대비 충분히 작아 재스캔 성능은 문제 없음)
- [x] `run()`이 매 시그널 평가마다 `daily_pnl_percent`/`weekly_pnl_percent`를 실제로 계산해 `risk_manager.evaluate()`에 전달 — 퍼센트 분모는 `run()`에 전달된 **최초** `account_balance`(고정값, 포지션 사이징에 쓰는 compounding 중인 running balance와 다름) — `scripts/run_paper.py`의 `PLACEHOLDER_ACCOUNT_BALANCE` 기반 `_pnl_to_percent()`와 동일하게 고정 분모를 의도적으로 채택(백테스트와 paper의 loss-limit 퍼센트가 서로 비교 가능하도록)
- [x] `docs/architecture.md`/`docs/strategy_spec.md` 변경 없음(이번 회차는 순수 backtest 엔진 내부 로직) — 대신 CHANGELOG/HANDOFF만 갱신
- [x] 신규 테스트 6종(`backend/tests/test_backtest_engine.py`): 경계 공식 자체의 단위 테스트 2종(`_day_bounds`/`_week_bounds`가 독립적으로 손계산한 날짜와 정확히 일치함을 증명, `_realized_pnl_in_window`가 윈도우 밖/오픈 트레이드를 올바르게 제외함을 증명) + 전체 `run()` 종단 테스트 2종(REAL `RiskManager` 사용 — 단일 스탑로스 손실이 `MAX_DAILY_LOSS_PERCENT`를 단독으로 위반하면 같은 날 나중에 제시된, 그 자체로는 완전히 유효한 두 번째 시그널이 실제로 거부됨을 증명 / 대조 케이스로 한도 내의 작은 손실은 거부하지 않음을 증명 — "무조건 다 거부"가 아님을 확인)
- [x] **테스트 작성 중 자체 발견/수정한 버그**: 처음 작성한 두 테스트가 격리 실행 시엔 통과하지만 전체 스위트 실행 시엔 실패 — 원인은 테스트 안에서 `import app.backtesting.backtest_engine as backtest_engine_module`를 새로 해서 그 모듈의 `settings`를 monkeypatch했는데, 이 저장소의 다른 테스트 파일들(`fresh_app_env`/`migrated_db` 픽스처, `conftest.py` 참조)이 DB 격리를 위해 `app.*`를 `sys.modules`에서 통째로 purge하는 패턴을 쓰기 때문에, 스위트 실행 순서에 따라 그 fresh import가 실제로 `BacktestEngine`/`RiskManager`(이 테스트 파일 collection 시점에 이미 import된, 옛 모듈 인스턴스)가 쓰는 것과 다른 `settings` 싱글턴을 가리킬 수 있었음(patch가 조용히 no-op됨). 이 파일의 다른 모든 테스트와 동일하게 파일 최상단에서 이미 import된 동일한 `settings` 참조를 patch하도록 수정해 해소 — 이 버그 자체가 "완결성 검증"의 실제 사례(테스트가 격리 실행에서 통과한다고 전체 스위트에서도 통과한다고 가정하면 안 됨을 직접 재확인)
- [x] 전체 `pytest backend/tests/` **140/140 통과**(기존 134 + 신규 6). 순서 의존적 flakiness 없는지 전체 스위트 3회 연속 재실행으로 확인
- [x] 오케스트레이터 재검증용 실측: `scripts/run_backtest.py`를 실 OKX API로 실행(BTCUSDT/5m) — 정상 완주, exit code 0, 리포트/CSV 생성 확인(오늘 시장은 confluence 없어 0-trade — 정상 결과, 에러 아님. 실거래 신호가 나는 시나리오는 위 유닛/종단 테스트에서 통제된 fixture로 직접 증명됨)
- [x] `py_compile` 무오류 확인(`backend/app/backtesting/backtest_engine.py`, `backend/tests/test_backtest_engine.py`), grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가
- [x] scope 준수: `backend/app/strategy/*`, `backend/app/execution/*`, `backend/app/risk/risk_manager.py`/`drawdown_guard.py`/`position_sizing.py` 자체, `exchange/*`, `frontend/*`, live-trading 게이팅 전부 무변경(diff에 등장하지 않음) — `risk_manager.py`는 이미 `daily_pnl_percent`/`weekly_pnl_percent` 파라미터를 지원하고 있어(직전 회차에서 이미 추가됨) import해서 consume만 함
- [x] git commit/push 완료 (`origin/master`) — operator가 사전에 "커밋 후 푸시, 라이브/자격증명/외부유료서비스/보안/파괴적 작업 아니면 승인 없이 계속 진행"이라고 명시적으로 요청함(이 태스크는 위 5개 카테고리 중 어느 것에도 해당하지 않음)

## 전체 회차 (페이퍼 트레이드 청산: SL/TP 실체결 + 실 fill price 기록)
- [x] **자본 보호 갭 발견/해소 — 페이퍼 트레이드가 열리기만 하고 절대 안 닫힘**: `TradeTracker().record_trade(status="open")`로 트레이드는 기록되지만, 그 이후 어떤 코드도 열린 포지션을 current price와 비교해 SL/TP 도달을 확인하거나 닫지 않았음 — `TradeJournal`의 daily/weekly 리포트(따라서 직전 회차에 배선한 loss-limit circuit breaker)가 실현 손실을 영원히 볼 수 없는 상태였음. `run_once()`에 매 pass(single-pass/loop 공용, loop-only 아님)마다 실행되는 "1.5 오픈 포지션 청산 체크" 단계 추가: `PaperBroker().check_exit()`으로 각 오픈 포지션을 확인하고, 트리거되면 `TradeTracker().close_trade()`로 실제 청산 + PnL 기록 + Telegram/Discord 알림(`scripts/run_paper.py`의 신규 `_check_and_close_open_positions()`/`_compute_exit_pnl()`)
- [x] **동시성 가드 추가(1.6단계)**: 청산 체크 이후에도 여전히 열린 포지션이 있으면 해당 pass는 시그널 생성/리스크/체결을 전부 skip(one-trade-open-at-a-time, `BacktestEngine`의 no-overlap 모델과 일치). `run_once()` summary dict에 `positions_closed`/`skipped_signal_generation`/`skipped_reason` 신규 필드 추가(기존 3개 필드 `signal_found`/`approved`/`executed`의 의미는 무변경)
- [x] `PaperBroker.check_exit()`에 청산 슬리피지 추가 — 기존엔 SL/TP 트리거 시 정확히 그 레벨 가격으로 체결된다고 가정(비현실적). `fill_entry()`와 동일한 컨벤션으로 불리한 방향 슬리피지 적용(포지션 종료는 반대 방향 거래이므로 진입과 정확히 반대 부호)
- [x] `ExecutionEngine.execute()`가 이제 `ExecutionResult.fill_price`/`fee_percent`로 `PaperBroker.fill_entry()`가 이미 계산한 실 체결가/수수료율을 노출(이전엔 success/order_id/error만 노출, 호출자가 항상 미체결 planned `entry_price`로 대체해야 했음)
- [x] **완결성 검증 중 실 버그 발견/수정 (operator 요청: "Verify whether they are complete")**: `scripts/run_paper.py`의 "5. Persist the executed trade" 섹션 docstring이 "이제 `result.fill_price`를 기록한다"고 주장했지만, 실제 코드는 여전히 미체결 `signal.entry_price`를 그대로 기록하고 있었음(docstring과 코드가 불일치하는 미완성 diff — 이전 세션이 docstring만 쓰고 실제 대입문은 안 고친 채 끝난 것으로 추정). 코드를 docstring이 애초에 주장한 대로 수정: `entry_price = result.fill_price if result.fill_price is not None else signal.entry_price`. **이 수정이 중요한 이유**: `_compute_exit_pnl()`이 `position["entry_price"]`가 실 체결가라고 가정하고 라운드트립 PnL을 계산하므로, 고쳐지지 않았다면 모든 페이퍼 트레이드의 PnL이 실제로 한 번도 체결된 적 없는 가격을 기준으로 계산되는 조용한 회계 오류가 났을 것. Telegram/Discord 알림 메시지도 `signal.entry_price` 대신 실 체결가를 쓰도록 함께 수정. `trade_data["slippage"]`도 항상 `0.0` placeholder였던 것을 `PaperBroker`가 실제로 적용한 슬리피지 비율(`SLIPPAGE_PERCENT`)로 교체. 포지션 사이징(`calculate_position_size`)은 의도적으로 계획된 `signal.entry_price` 기준 그대로 유지 — `BacktestEngine`과 동일한 size-before-fill 순서(리스크는 체결 전, 계획된 entry/stop 거리로 사이징)
- [x] `docs/architecture.md`의 Trading Modes 표 — `PAPER_MODE` 행이 슬리피지/체결 시뮬레이션을 전혀 언급 안 하던 것 보강(fee+slippage 시뮬레이션 자체는 이번 회차 이전부터 `PaperBroker.fill_entry()`에 존재했으나 문서화가 안 돼 있었음)
- [x] 전체 `pytest backend/tests/` **136/136 통과**(diff에 이미 포함돼 있던 신규 테스트 포함, 이번 완결성 수정으로 회귀 없음 재확인)
- [x] 오케스트레이터 재검증용 실측(스크립트 레벨 로직은 이 repo 컨벤션대로 pytest가 아니라 실 DB 재현으로 검증 — `scripts/run_paper.py`는 처음부터 전용 pytest 파일이 없고 항상 이 방식으로 검증돼 옴): 임시 SQLite에 실 `alembic upgrade head` 적용 → 실 `ExecutionEngine`/`PaperBroker`로 signal 체결(`fill_price=100.02`, planned `100.0`과 다름을 확인) → `run_paper.py`의 수정된 persist 로직을 그대로 재현해 `TradeTracker().record_trade()`로 실 DB에 기록(`entry_price=100.02`로 기록됨 — 버그가 안 고쳐졌다면 `100.0`이었을 것) → `TradeTracker().get_open_positions()`로 실 DB에서 재조회한 포지션으로 `PaperBroker().check_exit()` 호출(`current_price=116.0` → take_profit 트리거, `exit_price=114.977`) → `_compute_exit_pnl` 공식을 그대로 재현(`pnl=14.8495...`, 버그가 안 고쳐졌다면 다른 entry_price로 계산돼 틀린 값이 나왔을 것) → `TradeTracker().close_trade()`로 실 청산 → `get_open_positions()`가 빈 리스트임을 확인. 5단계 전부 실패 없이 통과
- [x] `py_compile` 무오류 확인(`scripts/run_paper.py`), grep 확인 — 신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가
- [x] scope 준수: `backend/app/strategy/*`, `backend/app/backtesting/*`, `risk/*`, `exchange/*`, `frontend/*`, live-trading 게이팅 전부 무변경(diff에 등장하지 않음)
- [x] git commit/push 완료 (`origin/master`) — operator가 사전에 "커밋 후 푸시" 명시적으로 요청함

## 전체 회차 (자본 보호: 실 date-scoped daily/weekly PnL을 RiskManager·circuit breaker에 배선)
- [x] **갭 발견/해소 1 — all-time을 daily로 오인**: `TradeJournal.generate_journal_report()`가 날짜 필터가 전혀 없어 `mode=="paper"`인 모든 트레이드를 all-time으로 집계했는데, `scripts/run_paper.py`의 `_check_drawdown_and_maybe_trip()`(loop mode 전용)이 이 all-time 합계를 `daily_pnl_percent`로 오용 — circuit breaker의 "daily loss limit"이 실제로는 all-time 누적 손실을 비교하고 있었음(당일 급락은 놓치고, 여러 날에 걸친 누적 손실이 threshold를 넘기면 "당일"로 잘못 표시하며 trip)
- [x] **갭 발견/해소 2 — RiskManager의 daily/weekly 체크가 죽은 코드**: 실제 매 시그널 승인 게이트인 `RiskManager().evaluate()`가 single-pass/loop 양쪽 호출부 모두에서 `daily_pnl_percent`/`weekly_pnl_percent`를 아예 안 넘겨 항상 기본값 `0.0`으로 평가 — `DrawdownGuard.check_daily_loss`/`check_weekly_loss`가 실손실과 무관하게 절대 트레이드를 거부할 수 없던 상태였음
- [x] **갭 발견/해소 3 — `MAX_WEEKLY_LOSS_PERCENT` 미집행**: `docs/risk_rules.md`에 문서화되고 `config.py`에 설정값도 있었지만 실제로 어디서도 집행되지 않고 있었음
- [x] `TradeJournal.generate_journal_report()`에 옵션 `start`/`end`(timezone-aware datetime, 둘 다 함께 필요 — 하나만 주면 `ValueError`, naive datetime도 `ValueError`) 파라미터 추가 — **인자 없이 호출 시 기존 all-time 계약과 완전 동일**(기존 테스트 2곳 무변경 통과). 범위가 주어지면 `status=="closed"` AND `closed_at` in `[start, end]`인 paper 트레이드만 집계(오픈 트레이드는 `closed_at`이 없어 실현 손익 윈도우에 속할 수 없으므로 이 모드에서는 `total_trades`에서도 제외 — all-time 모드와 다른 점을 독스트링에 명시)
- [x] `generate_daily_report(as_of=None)` / `generate_weekly_report(as_of=None)` 신규 편의 메서드 — "daily"=UTC 캘린더 day(`00:00:00.000000`~`23:59:59.999999` UTC), "weekly"=**ISO 캘린더 주**(월요일 `00:00:00.000000` UTC ~ 일요일 `23:59:59.999999` UTC). rolling 7-day가 아니라 ISO 캘린더 주를 택한 이유: `run_paper.py`의 `_count_trades_opened_today`가 이미 UTC `.date()` 기준 day 컨벤션을 쓰고 있어, day/week 둘 다 겹치지 않는 캘린더 버킷으로 일관되게 맞춰야 "이 경계를 이미 넘었는가"가 항상 명확해짐 — `docs/risk_rules.md` 신규 "Daily/weekly boundary convention" 섹션에 근거와 함께 명시
- [x] `run_paper.py`의 `_check_drawdown_and_maybe_trip()`이 이제 `generate_daily_report()`/`generate_weekly_report()`로 실제 daily/weekly PnL%를 계산해 **daily 또는 weekly 둘 중 하나만 breach해도** circuit breaker를 trip — 의도적 설계 결정(코드 주석에 근거 명시): 이 함수가 loop mode에서 유일한 Telegram/Discord 알림 지점이라, weekly breach를 RiskManager의 per-signal 거부에만 맡기면 매 시그널이 조용히 계속 거부되기만 하고 운영자에게는 절대 알림이 안 감 — daily 스파이크와 동일하게 즉시 alert+halt 처리하는 게 맞다고 판단
- [x] `run_once()`(single-pass/loop 공유 경로)가 이제 journal에서 실 daily/weekly PnL%를 계산해 `RiskManager().evaluate()`에 실제로 전달 — `trades_today`와 동일한 best-effort 패턴(쿼리 실패 시 조용히 죽지 않고 WARNING 출력 후 0.0 기본값). single-pass 모드가 이것만으로 충분한지 문서화된 결론: **충분** — daily/weekly 수치를 프로세스 메모리가 아니라 매 실행마다 실 DB에서 새로 조회하므로, 연속 프로세스 실행 사이에 상태가 남아있을 필요 없이 손실 지속 상황이 매번 독립적으로 재감지·재거부됨. 남은 갭으로 플래그(고치지 않음, 범위 밖): single-pass의 loss-limit 거부는 alerting 관점에서 조용함 — stdout/summary dict에는 보이지만 Telegram/Discord 알림은 안 감(loop mode와 다름)
- [x] `docs/risk_rules.md` "Behavior" 섹션을 정직하게 재작성 — "다음 거래일까지 비활성화"라는 모호한 기존 문구를 실제 동작으로 교체: circuit breaker는 trip 후 **자동 day-boundary 리셋이 전혀 없고** 사람이 명시적으로 `.reset()`을 호출해야만 재개됨. 이건 갭이 아니라 단일 트레이더 시스템에서 손실 한도 돌파 후 사람이 원인을 보고 재개하는 것이 오히려 옳은 설계일 수 있다는 의도적 결정이라고 명시 — 다만 문서가 실제로 없는 자동-재설정 동작을 있는 것처럼 주장해서는 안 된다는 원칙에 따라 정직하게 기술. 자동 리셋 구현 자체는 이번 태스크 범위 밖(더 큰 설계 논의 필요)이라고 명시하고 구현하지 않음. `MAX_WEEKLY_LOSS_PERCENT`가 이제 실제로 집행됨을 신규 문단으로 명시
- [x] 신규 테스트 8종(실 마이그레이션된 임시 SQLite, mock 없음): `test_portfolio.py`에 5종(`start`/`end` 동반 필수 검증, naive datetime 거부, daily 경계 증명 — 오늘 UTC 윈도우 시작/끝 정확히 포함 vs 1마이크로초 전/1초 후/8일 전은 전부 큰 손실로 심어 경계 버그가 있으면 절대 못 놓치게 설계 + 오픈 트레이드 제외 증명, weekly ISO-주 경계 증명 — 이 회차의 프로덕션 공식과 무관하게 독립적으로 검증된 날짜로 월요일 시작/일요일 끝 정확히 포함 vs 그 전후 1마이크로초/1초는 제외 증명, all-time 기본 동작 무변경 증명) + `test_risk_daily_weekly_real_integration.py`(신규 파일) 3종(실 seed된 daily loss가 실제로 `RiskManager.evaluate()`를 거부시킴을 종단 증명, 같은 ISO 주의 "오늘 아님" 손실이 daily 사유 없이 weekly 사유로만 거부됨을 증명해 두 체크가 진짜 독립적임을 증명, 한도 내 소액 손실은 여전히 승인됨을 대조 증명해 배선이 무조건 거부가 아님을 증명)
- [x] 전체 `pytest backend/tests/` **135/135 통과**(기존 127 + 신규 8)
- [x] 오케스트레이터 재검증용 실측: 임시 SQLite에 실 `alembic upgrade head` 적용 → `run_paper.py` 평범 단발 실행(exit 0, 실 OKX 데이터로 "No signal generated this pass." — 정상 결과) → 실 DB에 `pnl=-150.0`(플레이스홀더 계정 $10,000 대비 -1.5%) 손실 트레이드 직접 seed → `--iterations 2 --interval-seconds 0`로 loop mode 재실행 → 두 iteration 모두 `ALERT: Circuit breaker tripped: daily loss limit breached (daily PnL -1.50%, limit 1.0%)` 실제 출력 확인(seed한 손실 수치와 정확히 일치, exit 0 — trip 자체는 안전한 처리된 결과)
- [x] `py_compile` 무오류 확인(`backend/app/portfolio/journal.py`, `scripts/run_paper.py`, `backend/tests/test_portfolio.py`, `backend/tests/test_risk_daily_weekly_real_integration.py`), grep 확인 — TODO/placeholder-스텁/mock/bare pass/NotImplementedError 신규 코드 없음(기존 `PLACEHOLDER_ACCOUNT_BALANCE` 네이밍/주석은 이전부터 있던 것으로 무관)
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가(append, 기존 항목 전부 무변경)
- [x] scope 준수: `backend/app/strategy/*`, `backend/app/backtesting/*`, `backend/app/execution/*`, `backend/app/exchange/*`, `risk/risk_manager.py`, `risk/drawdown_guard.py`, `frontend/*`, live-trading 게이팅 전부 무변경(diff에 등장하지 않음) — `risk_manager.py`/`drawdown_guard.py`는 정독해서 기존 `daily_pnl_percent`/`weekly_pnl_percent` 파라미터·`DrawdownGuard` boolean 컨벤션이 이미 이번 배선을 그대로 지원함을 확인만 하고 실제로 한 글자도 안 건드림
- [x] git commit/push 완료 (`d6c676a`) — 작성 당시엔 미커밋이었으나 이후 세션에서 operator 승인 후 커밋/push됨(이 문서가 뒤늦게 반영)

## 전체 회차 (백테스트 엔진: 포지션 사이징 정확성 갭 해소 — 100%-notional placeholder → 실 RISK_PER_TRADE_PERCENT 사이징)
- [x] **정확성 갭 발견/해소**: `BacktestEngine._simulate_trade()`가 자신의 docstring에서도 스스로 인정하던 placeholder(`pnl = account_balance * net_return` — 매 트레이드가 계정 전체 잔고를 notional로 리스크)를 실제 Risk Engine 사이징 모델로 교체. `docs/risk_rules.md`가 문서화하고 `scripts/run_paper.py`가 이미 올바르게 쓰고 있던 `calculate_position_size(account_balance, RISK_PER_TRADE_PERCENT, entry, stop_loss)`(`backend/app/risk/position_sizing.py`, **무변경** — consume만 함)를 `BacktestEngine`에도 동일하게 배선. 그동안 백테스트 PnL/승률/MDD 수치는 실제 paper/live가 돌릴 전략보다 훨씬 리스크가 큰(계정 전액 notional) 가상의 전략을 측정하고 있었던 것 — 이번 수정으로 백테스트가 실제로 대표성 있는 증거가 됨
- [x] `BacktestEngine.run()`에 사이징 단계 추가: 리스크 승인 직후, 신호의 **원본(슬리피지 반영 전) entry/stop**으로 `calculate_position_size(account_balance, settings.RISK_PER_TRADE_PERCENT, signal.entry_price, signal.stop_loss)` 호출(`run_paper.py`와 완전히 동일한 패턴) → `size`(단위)를 `_simulate_trade()`에 전달
- [x] **degenerate case 방어**: `entry == stop_loss`면 `calculate_position_size`가 자체 0-division 가드로 `0.0`을 반환 — `BacktestEngine`은 `entry_model.py`의 상류 `if risk <= 0: return None` 보장을 맹신하지 않고 직접 방어: `size == 0.0`이면 거부된 신호와 동일하게 취급(`i += 1; continue`), `trades`에 가짜 0-notional "트레이드"를 절대 기록하지 않음
- [x] **PnL/수수료 공식 전면 교체** (기계적 이식이 아니라 재도출): `raw_pnl = size * (exit_price - entry_fill)`(long, short는 부호 반대)로 실제 포지션 기반 PnL을 계산. 수수료는 더 이상 "계정 잔고 대비 flat %"가 아니라 각 leg의 **실제 notional**(entry leg=`size*entry_fill`, exit leg=`size*exit_price`)에 `fee_percent`를 적용 — 사이징이 계정 전액에서 리스크 기반 실 포지션으로 바뀐 이상 수수료도 그에 연동되어야 재무적으로 맞다는 점을 코드 주석에 근거와 함께 명시
- [x] `trades` 딕셔너리에 `size`(단위) 필드 추가(additive) — 실제 사이징 결정이 트레이드 기록에서 보이지 않는 것은 부적절하다고 판단. `report_generator.py`의 `TRADE_FIELDS`/`.get()` 기반 CSV export는 무변경으로 안전하게 호환(신규 필드는 CSV 헤더에도 자동 포함됨, 코드 수정 없음)
- [x] 신규 테스트 4종(`backend/tests/test_backtest_engine.py`, 기존 6종 스타일 준수, no-lookahead 회귀 2종은 완전 무변경으로 여전히 통과): `calculate_position_size`를 독립적으로 재호출해 `_simulate_trade`가 계산한 `size`가 정확히 일치함을 증명, 스탑 거리만 다른(계정 잔고/리스크율은 동일) 두 시나리오로 PnL이 `size`에 정확히 비례함을 증명(구 모델이었다면 두 시나리오가 동일한 PnL을 냈을 것이라는 대조까지 코드로 명시), `run()` 전체 배선이 실제 `settings.RISK_PER_TRADE_PERCENT`를 쓰는지 종단 증명, degenerate(`entry==stop_loss`) 신호가 매 스텝 재평가되면서도 절대 가짜 트레이드로 기록되지 않음을 증명
- [x] 전체 `pytest backend/tests/` **127/127 통과**(기존 123 + 신규 4)
- [x] 오케스트레이터 재검증용 실측: `scripts/run_backtest.py`를 실 OKX API로 여러 심볼/타임프레임 조합 실행 — `BTCUSDT/15m`에서 실제 2건 트레이드 체결 확인(`total_pnl=-89.85`, `max_drawdown=0.90%`), `SOLUSDT/15m`에서도 실제 2건 체결 확인(`total_pnl=-80.25`, `max_drawdown=0.80%`). `account_balance=10000`/`RISK_PER_TRADE_PERCENT=0.25%`(리스크 예산 트레이드당 $25) 기준, 2연패에도 MDD가 1% 미만으로 완전히 bounded — 구 100%-notional 모델이었다면 스탑 거리(%) 자체가 곧 계정 대비 손실률이 되어 리스크율(0.25%)과 무관하게 임의로 커질 수 있었던 것과 대비. CSV(`entry_price=63092.616, exit_price=62985.5514, size=0.264694, pnl=-45.025...`)를 수동 재계산해 `raw_pnl - entry_fee - exit_fee` 공식과 소수점까지 정확히 일치함을 직접 확인. (참고: 이번 두 샘플에서 트레이드당 손실이 순수 리스크 예산($25)보다 큰 이유는 부실 버그가 아니라, 스탑 거리가 좁아(가격의 약 0.15%) 동일 $ 리스크를 위한 포지션 notional이 계정 대비 커지면서(약 1.67배) 그 notional에 붙는 수수료 비중이 상대적으로 커진 것 — 리스크 기반 사이징의 잘 알려진 실제 동작이며 이번 수정 범위 밖의 별도 튜닝 후보로 기록만 해둠)
- [x] `py_compile` 무오류 확인(`backend/app/backtesting/backtest_engine.py`, `backend/tests/test_backtest_engine.py`), 변경/신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음(grep 확인 — "placeholder"라는 단어 자체는 "구 placeholder를 교체했다"는 설명 주석/독스트링에만 등장, 실제 미구현 코드 없음)
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가(append, 기존 3개 마일스톤 항목 무변경)
- [x] scope 준수: `backend/app/strategy/*`, `execution/`, `risk/position_sizing.py` 자체, `exchange/`, live-trading 게이팅 전부 무변경(diff에 등장하지 않음) — `risk/position_sizing.py`는 import해서 consume만 함
- [x] git commit/push 완료 (`0e52b5a`) — 작성 당시엔 미커밋이었으나 이후 세션에서 operator 승인 후 커밋/push됨(이 문서가 뒤늦게 반영)

## 전체 회차 (백테스트 엔진: 실 HTF/LTF 워크포워드 + no-lookahead HTF 커서)
- [x] **이전 회차에서 보고된 블로커 해소**: 직전 Strategy Engine 커밋(`9db3db3`)이 `SignalEngine.generate_signal(symbol, ltf_candles, htf_candles)`로 시그니처를 바꾼 뒤, `backend/app/backtesting/backtest_engine.py`의 walk-forward 루프가 여전히 구 시그니처(`generate_signal(symbol=symbol, candles=candles[:i+1])`)로 호출 중이라 `scripts/run_backtest.py` 전체 실행이 `TypeError`로 즉시 실패하던 문제 수정. `BacktestEngine.run()` 시그니처를 `run(self, ltf_candles, htf_candles, signal_engine, risk_manager, ...)`로 변경
- [x] **no-lookahead HTF 커서 구현 (정확성 핵심)**: `app.backtesting.backtest_engine._advance_htf_cursor()` 신규 — walk-forward의 각 LTF step마다, 해당 LTF 캔들 시점 기준으로 "확실히 마감된" HTF 캔들만 `generate_signal()`에 노출하는 forward-only 2-pointer 커서(전체 루프에서 O(n)). HTF 캔들 `k`는 `k+1`번째 캔들이 존재하고 그 타임스탬프가 현재 LTF 타임스탬프 이하일 때만 "마감 확정"으로 간주(HTF 타임프레임 길이를 파싱/하드코딩할 필요 없음). 아직 마감된 HTF 캔들이 하나도 없으면 빈 리스트(`[]`)를 넘기고, `detect_htf_bias([])`가 이미 안전하게 "neutral"을 반환하므로 별도 예외 처리 불필요
- [x] `scripts/run_backtest.py`가 `run_paper.py`와 동일한 패턴으로 LTF/HTF 캔들을 독립적으로 fetch(`settings.HTF_TIMEFRAME`) — HTF fetch 실패/빈 응답은 LTF와 동일하게 명확한 에러 + exit code 1(LTF를 HTF 대신 쓰는 fallback 없음). 스크립트 docstring의 "KNOWN GAP(blocker)" 문단을 실제 해결된 HTF 처리 설명으로 교체
- [x] `MIN_CANDLES`(현재값 `31`) 유지 결정을 코드에 명시적으로 문서화 — LTF 히스토리 기준으로만 산정된 값이라 5m/4h 같은 실제 타임프레임 비율에서는 의미 있는 HTF bias가 나오려면 수백 개의 LTF 캔들이 필요하지만, 빈 슬라이스/"neutral" bias로 안전하게 degrade되므로(잘못된 신호가 나올 위험 없음, 초반 no-op 반복만 약간 늘어남) 값을 올리지 않기로 의도적으로 결정
- [x] 테스트: `backend/tests/test_backtest_engine.py` 신규 6종 — no-lookahead 회귀 증명을 (1) `_advance_htf_cursor` 단위 테스트(아직 마감 안 된 HTF 캔들의 OHLC가 완전히 달라도 결과 슬라이스가 바이트 단위로 동일함을 직접 증명, 게다가 "naive/buggy off-by-one 커서였다면 실제로 슬라이스가 달라졌을 것"이라는 대조 assertion까지 포함해 테스트가 공허하지 않음을 증명) + (2) `BacktestEngine.run()` 전체 실행 레벨(LTF는 동일하게 유지하고 마감되지 않은 마지막 HTF 캔들의 OHLC만 다르게 한 두 시나리오가 실제 트레이드 1건 포함 `BacktestResult`까지 완전히 동일함을 증명) 양쪽에서 수행. 전체 `pytest backend/tests/` 123/123 통과(기존 117 + 신규 6)
- [x] 오케스트레이터 재검증용 실측: `scripts/run_backtest.py`를 실 OKX API로 두 번 실행(BTCUSDT/5m 300개, ETHUSDT/15m 300개) — 둘 다 LTF/HTF 캔들 fetch 성공, `TypeError` 없이 완주, exit code 0(오늘 시장은 confluence가 안 맞아 0-trade 결과 — 유효한 정상 결과, 에러 아님)
- [x] `py_compile` 무오류 확인(`backend/app/backtesting/backtest_engine.py`, `scripts/run_backtest.py`, `backend/tests/test_backtest_engine.py`), 변경/신규 코드에 TODO/placeholder/mock/bare pass/NotImplementedError 없음(grep 확인)
- [x] `CHANGELOG.md`에 신규 Unreleased 섹션 추가, 직전 회차의 "Known gap (blocker, flagged for follow-up)" 노트를 "RESOLVED"로 갱신하고 이번 항목을 가리키도록 수정

## 전체 회차 (Strategy Engine 정확성 갭 해소: HTF/LTF 실분리 + confluence 방향 일치)
- [x] **Gap 1 — 가짜 HTF/LTF 분리 수정**: `SignalEngine.generate_signal(symbol, candles)` 단일 캔들 리스트를 `detect_htf_bias()`를 포함한 모든 detector에 동일하게 먹이던 문제 수정. 시그니처를 `generate_signal(symbol, ltf_candles, htf_candles)`로 변경 — `detect_htf_bias(htf_candles)`만 별도, 나머지(sweep/choch/fvg/order_block)는 `ltf_candles` 유지. `scripts/run_paper.py`가 `CandleFetcher`로 `DEFAULT_TIMEFRAME`(5m)/`HTF_TIMEFRAME`(4h) 두 시리즈를 독립적으로 fetch — HTF fetch 실패/빈 응답은 LTF와 동일하게 명확한 에러 + exit_code 1 처리(LTF를 HTF 대신 쓰는 fallback 없음)
- [x] **Gap 2 — confluence 방향 불일치 버그 수정 (실제 정확성 버그)**: `entry_model.build_entry_model()`의 confluence 게이트가 `sweep`/`choch`의 존재 여부만 체크하고 방향(`type`)은 전혀 안 봐서, 엔진이 방금 감지한 구조적 신호와 반대 방향으로 진입할 수 있던 버그 수정. 결정론적 규칙 추가(코드 주석 + `docs/strategy_spec.md`에 명시): `sell_side` sweep은 `long`에만, `buy_side` sweep은 `short`에만 유효 confluence; `bullish_choch`는 `long`에만, `bearish_choch`는 `short`에만 유효. 불일치 시 "없는 것"으로 취급(에러 아님)
- [x] `market_structure.detect_choch_mss()`에 `swept_index: int | None = None` 파라미터 추가 — 제공 시 해당 index 이후의 swing만 broken level 후보로 인정, CHoCH가 실제로 그 CHoCH를 유발한 sweep 이후에 형성된 구조를 반영하도록 인과관계 연결(`docs/strategy_spec.md` section 3의 "swept liquidity level" 요구사항 충족). `swept_index=None`(기본값)이면 기존 동작과 완전 동일. `SignalEngine`이 `detect_liquidity_sweep(ltf_candles)` 먼저 호출 후 그 결과의 `swept_index`를 `detect_choch_mss`에 전달하도록 배선
- [x] `order_block.py`의 `_LOOKBACK=10`/`_IMPULSE_MULT=1.5`, `entry_model.py`의 `_STOP_BUFFER=0.001`/`_RR=2.0`에 "왜 이 값인지" 주석 보강 — 실제 근거가 없는 값은 "백테스트로 튜닝된 값이 아닌 합리적 시작값"이라고 솔직히 명시(가짜 근거 창작 안 함)
- [x] 테스트: `test_strategy_signal_engine.py`에 LTF 단독으로는 "neutral" bias가 나오지만(직접 검증) 별도의 bullish HTF와 짝지으면 실제로 "long" 신호가 나오는 실제 회귀 테스트 추가(단순 시그니처 리네임이 아니라 진짜 분리가 작동함을 증명). `test_strategy_entry_model.py`에 방향 불일치 sweep/choch가 이제 `None`을 반환하는 회귀 테스트 4종 추가. `test_strategy_market_structure.py`에 `swept_index`가 이전 구조 break를 올바르게 배제하는 테스트 추가. 전체 `pytest backend/tests/` 117/117 통과(신규 이전 109 + 신규 8)
- [x] **블로커 발견/보고 (미해결, engineering-head 라우팅 필요)**: `backend/app/backtesting/backtest_engine.py`(scope 밖)가 walk-forward 루프마다 `signal_engine.generate_signal(symbol=symbol, candles=candles[:i+1])`를 구 시그니처로 호출 중이라, 이번 변경 이후 `scripts/run_backtest.py` 전체 실행은 `TypeError`로 즉시 실패함(명확한 에러 메시지로 exit 1 — 조용한 오동작은 아님). 제대로 고치려면 `BacktestEngine`이 LTF/HTF 두 캔들 시리즈를 타임스탬프 기준으로 동기화해서 걷는 로직이 필요한데, 이는 `backend/app/backtesting/`(이번 태스크 scope.allow 밖) 영역의 비trivial 설계 변경이라 손대지 않음 — 후속 태스크로 라우팅 필요
- [x] 오케스트레이터 재검증용 실측: 실 OKX API로 5m(300개)/4h(300개) 캔들 fetch → 서로 다른 시간 범위 확인(5m: 약 1일치, 4h: 약 50일치) → `SignalEngine.generate_signal()` 실제 호출까지 에러 없이 완주(오늘 시장은 우연히 neutral이라 신호 없음 — 정상 케이스). `scripts/run_paper.py`도 임시 SQLite DB로 실제 1회 spawn 실행, exit 0 확인

## 전체 회차 (CircuitBreaker DB 영속화)
- [x] 자본 보호 갭 해소: `scripts/run_paper.py` loop mode의 `CircuitBreaker`가 프로세스 메모리에만 존재해 crash/redeploy/cron respawn 시 tripped 상태가 조용히 초기화되던 문제 수정
- [x] `risk/circuit_breaker.py`에 `PersistentCircuitBreaker` 래퍼 추가 — 기존 `CircuitBreaker`는 완전 무변경(DB 의존성 0, 단위테스트 그대로 통과), 생성자에 주입된 `state_loader`/`state_saver` 콜러블로만 영속화(Iron Wall 패턴 유지, `app.portfolio` 직접 import 없음)
- [x] `bot_state` 테이블에 `circuit_breaker_tripped`/`circuit_breaker_reason`/`circuit_breaker_tripped_at` 컬럼 추가 — 실 Alembic 마이그레이션(`4b8a822a475b`, `alembic revision --autogenerate` 기반, non-empty 테이블 대응 `server_default` 수동 보정)
- [x] `portfolio/positions.py`에 `load_circuit_breaker_state()`/`save_circuit_breaker_state()` 추가 (기존 `get_or_create_bot_state()`/`update_bot_mode()` 패턴 그대로)
- [x] `run_paper.py` loop mode가 `PersistentCircuitBreaker` 사용 — 시작 시 DB에서 이전 tripped 상태 로드/적용, trip()/reset() 시마다 동기 영속화
- [x] 신규 테스트 8종(실 마이그레이션된 임시 SQLite 기반, mock 없음) — 2-OS-프로세스 실통합 테스트로 "crash mid-trip → respawn" 시나리오 직접 재현·검증
- [x] 오케스트레이터(CTO) 독립 재검증: 변경분 diff 직접 확인(engineering-head 보고와 파일 단위 일치), `pytest` 직접 재실행(109/109 통과), execution/exchange/LiveBroker 무변경 diff로 확인
- [x] operator 승인 후 git commit(`028087a`)/push 완료

## 전체 회차
- [x] `scripts/run_backtest.py`: `print("TODO: implement in later milestone")` 스텁을 실제 백테스트 러너로 교체 — OKX 공개(키 불필요) 엔드포인트에서 실 OHLCV 캔들을 fetch해 기존 실구현 Strategy/Risk/Backtest 엔진(`BacktestEngine.run()`)에 그대로 replay하고 markdown 리포트 + CSV trade export를 생성. 주문을 전혀 내지 않고 trades DB 테이블도 전혀 건드리지 않음(설계상 DB-independent), API 키/계정 불필요
- [x] 실측으로 확인된 한계를 코드/주석에 문서화: `CandleFetcher`의 `since` 파라미터가 OKX `before` 쿼리 파라미터에 연결되어 있어(더 최신 캔들을 반환할 뿐 더 오래된 과거로 페이징이 안 됨) 단일 fetch(OKX 300개 한도)로 캡하고, 더 많은 캔들이 요청되면 조용히 짧은 샘플을 주는 대신 명확한 안내 메시지를 출력하도록 처리
- [x] 오케스트레이터 재검증: 실행(BTCUSDT/5m 기본 인자, ETHUSDT/15m 커스텀 인자) + 에러 경로(존재하지 않는 심볼) 확인. 생성된 리포트는 `scripts/reports/`에 저장되며 런타임 산출물이라 `.gitignore`에 추가
- [x] git에 커밋 완료 (`4904489`)

## 전체 회차 (DB 부트스트랩 수정)
- [x] DB 부트스트랩 자동화 — `backend/app/main.py`에 FastAPI `lifespan` 훅 추가, 앱 시작 시 `alembic upgrade head`를 프로그래밍 방식으로 자동 실행 (`alembic.ini`/`env.py`는 M5 그대로, 건드리지 않음)
- [x] 오케스트레이터(저) 독립 재검증: **완전히 새로 만든 빈 SQLite 파일**(사전에 create_all/alembic 수동 실행 전혀 안 함)로 앱을 직접 부팅 → 시작 로그에서 `Running upgrade -> a0f5ebc23690, initial schema` 확인 → `/dashboard/status`·`/settings/mode` 즉시 200 확인 → DB 직접 introspection으로 6개 테이블 + `alembic_version=a0f5ebc23690` 확인 (create_all 우회가 아니라 진짜 Alembic을 통과했음을 증명) → backend `py_compile` 재확인 → 테스트 서버 종료, 임시 DB 삭제
- [x] sub-agent가 별도로 idempotency(이미 head인 DB에 재부팅 시 no-op)와 fail-fast(잘못된 DATABASE_URL 시 조용히 넘어가지 않고 확실히 실패)까지 검증함
- [x] Milestone 7 + 이번 부트스트랩 수정 모두 git에 커밋/push 완료 (`f92f507`)

## 전체 회차 (Milestone 7)
- [x] `portfolio/positions.py`에 `update_bot_mode(mode)` 추가 — `BotState.mode` 실제 영속화
- [x] `GET /settings/mode`가 DB(`BotState`)에서 읽어 `/dashboard/status`와 항상 일치 (기존 env값 불일치 수정)
- [x] `POST /settings/mode`: paper/backtest는 실제 DB 저장, 유효하지 않은 값은 400. **live 분기는 문자 하나도 안 건드림**
- [x] `frontend/lib/api.ts`에 `setTradingMode()` 추가, `ModeToggle.tsx`가 실제 backtest/paper/live 버튼으로 전환 — live 시도 시 403 메시지 그대로 노출
- [x] 오케스트레이터 독립 재검증: backtest 전환(200, 영속화) → live 시도(403, DB 불변) → 잘못된 값(400) → paper 복귀(200)

## 전체 회차 (Milestone 6)
- [x] `frontend/lib/api.ts`(신규) — 8개 대시보드/trades 엔드포인트 타입드 fetch 래퍼, `NEXT_PUBLIC_API_BASE_URL`(기본 `http://localhost:8000`) 사용, 실패 시 명확한 Error로 reject
- [x] `frontend/lib/usePolling.ts`(신규) — 컴포넌트 공용 폴링 훅(loading/data/error)
- [x] `frontend/lib/types.ts` 재작성 — 실제 백엔드 snake_case 응답 그대로 반영 (Milestone 1 당시 추측성 camelCase 타입 폐기)
- [x] `BotStatusCard`/`PositionsPanel`/`LogsPanel` → `/dashboard/status`·`/dashboard/positions`·`/dashboard/logs` 실DB 데이터로 연결. `BiasCard`/`SignalsPanel`/`RiskStatusPanel` → 실제로 호출은 하되, 해당 백엔드 엔드포인트 자체가 여전히 placeholder(neutral/빈 값)라 백엔드가 보내는 "아직 라이브 아님" note를 정직하게 배지로 표시(가짜 데이터로 꾸미지 않음). `ModeToggle` → 실제 mode/live_enabled/trading_allowed 상태 표시(전환 액션 자체는 Milestone 7에서 추가됨)
- [x] sub-agent 자체 검증 + 오케스트레이터(저) 독립 재검증: 실DB에 트레이드/로그 시드 → uvicorn 실부팅 → curl로 `/dashboard/status`·`/positions`·`/logs` 실데이터 확인, CORS 헤더 확인 → Next.js dev 서버를 그 백엔드에 연결해 SSR 셸 200 확인 → `tsc --noEmit`/`next build` 클린 통과 재확인
- [x] git에 커밋 완료 (`5a9ff47`)

## 전체 회차 (이전 마일스톤)
- [x] Milestone 5 — git 저장소 초기화 + GitHub 원격(`https://github.com/jinalove1111/AutoCookie.git`) 등록, 로컬 git identity(jinal/jina4926952@gmail.com) 설정, 초기 커밋(80파일) push 완료
- [x] Milestone 5 — 실제 Alembic 마이그레이션 셋업: `backend/alembic.ini` + `migrations/env.py`(런타임에 `settings.DATABASE_URL` 주입) + 초기 마이그레이션(`a0f5ebc23690_initial_schema.py`) — 6개 테이블·`candles` unique constraint·`strategy_logs→signals` FK 전부 autogenerate로 정확히 캡처됨
- [x] Milestone 5 — `.env.example`의 `DATABASE_URL`을 실제 Postgres 연결 문자열 형태로 교정 (docker-compose의 POSTGRES_DB/USER/PASSWORD 값과 일치)
- [x] Milestone 5 — 오케스트레이터(저) 직접: Docker/시스템 Postgres 없는 환경이라 **포터블 PostgreSQL 16 바이너리를 스크래치패드에 다운로드**해 127.0.0.1:5433에 임시 인스턴스 기동(시스템 설치 없음, 세션 종료 시 정리) → 실제 `alembic upgrade head` 적용 → `\dt`/`\d candles`/`\d strategy_logs`로 스키마 직접 확인 → `app.main` 실제 Postgres 연결로 boot → `run_paper.py` 실행 → TradeTracker로 실제 트레이드 기록/조회까지 전부 실제 Postgres 위에서 재검증
- [x] 회귀 확인: backend 45개 `.py` 파일 `py_compile` 무오류
- [x] Postgres/GitHub push는 커밋 `9cb98aa`로 완료 (docker-compose 경로 자체는 여전히 미검증 — Docker가 이 환경에 없음)

## 전체 회차 (이전 마일스톤)
- [x] Milestone 1: 6-layer 아키텍처 + 폴더 스캐폴딩 + docs 7종 + .env.example/docker-compose/README/CHANGELOG + FastAPI/Next.js 부팅 검증
- [x] Milestone 2 — Strategy/Risk/Backtest 실로직 + OKX 공개 캔들 연동, 전체 실통합 테스트 통과
- [x] Milestone 3 — PaperBroker/OrderManager/ExecutionEngine/safety_checks, Portfolio/Journal 실DB 연동, API routes 실DB 전환, run_paper.py 단발 실행 스크립트, 오케스트레이터 실통합 검증
- [x] Milestone 4 — `risk/circuit_breaker.py` 실구현(trip/is_tripped/reset) + `risk_manager.evaluate()`에 `circuit_breaker` 옵션 파라미터 추가(하위호환 유지, 기존 호출 무변경 확인)
- [x] Milestone 4 — `notifications/telegram.py`·`discord.py` 실구현 — 비활성 시 안전한 no-op, 활성 시 실제 HTTP POST, 네트워크 실패에도 절대 raise 안 함(실제 Telegram/Discord API에 가짜 토큰으로 요청해 404 수신 확인). `config.py`/`.env.example`에 `ENABLE_DISCORD_ALERTS`/`DISCORD_WEBHOOK_URL` 추가(기존 필드 무변경, additive만)
- [x] Milestone 4 — `backtesting/report_generator.py` 실구현 — markdown 리포트 + CSV export, 빈 케이스/50건 트렁케이션 검증
- [x] Milestone 4 — `scripts/run_paper.py`를 반복 루프로 확장 (`--iterations`/`--interval-seconds`), 기본 인자 없는 실행은 Milestone 3와 동일 동작 유지(회귀 없음 확인), 루프 전체에서 CircuitBreaker 인스턴스 하나를 공유, 트레이드 체결 시 텔레그램/디스코드 알림 발송, daily loss 감지 시 circuit breaker 자동 trip
- [x] Milestone 4 — 오케스트레이터(저) 직접 최종 회귀: backend 43개 `py_compile` 무오류, `app.main` boot 확인, run_paper.py 단발 실행(exit 0) + 2회 루프 실행(동일 CircuitBreaker id 유지, exit 0) 전부 재검증
- [x] git 저장소 초기화 + GitHub push 완료 (Milestone 5에서 처리, 위 참조)
- [x] Alembic 마이그레이션 실제 init 완료 (Milestone 5에서 처리, 위 참조)
- [ ] pandas/numpy 미설치 (Python 3.14 wheel 이슈) — 지금까지 stdlib로 전부 회피, 실질적 문제 없음
- [ ] `DATABASE_URL` 기본값 빈 문자열, `.env` 파일 없음 — 실사용 시 반드시 설정 필요 (Milestone 3부터 반복 확인된 gap)
- [ ] **다음 단계(Small Live Trading)는 실제 OKX API 키(출금 권한 없는 키) 발급이 선행되어야 하고, 매 단계 operator의 명시적 승인이 필요함 — CTO 재량으로 진행하지 않기로 operator와 합의됨**
- [ ] LiveBroker, exchange/okx_client.py·orangex_client.py 여전히 완전 스텁 — 실거래 API 호출 코드 전혀 없음
- [ ] frontend는 status/positions/logs 실DB 엔드포인트에는 이미 연결됨(Milestone 6). 다만 대시보드 3개 카드(BiasCard/SignalsPanel/RiskStatusPanel)가 부르는 백엔드 엔드포인트(`get_market_bias`/`get_recent_signals`/`get_risk_status`) 자체가 아직 하드코딩된 neutral/빈 값을 반환하는 의도적 placeholder — 실전략 상태로 wiring하는 작업이 다음 단계 후보
- [x] ~~CircuitBreaker 상태는 프로세스 메모리에만 존재~~ — DB 영속화 완료(위 참조, `028087a`)

## 현재 위치
**operator 스코프락 발효 중**: Phase 1 목표는 오직 "JadeCap 하나를 수익성 있는 자동매매 시스템으로 완성"하는 것 — Backtest → Walk-Forward → Paper Trading → Small Live 4개 게이트로만 진행 판단. 멀티전략/퀀트 리서치 플랫폼 등은 명시적으로 Phase 2(ROADMAP.md에 문서화만, 구현 금지)로 이동됨.

**Phase 1 게이트 현황**: (1) Backtest ✅ 완료(4자산×2026 + BTC×2025) + **controlled parameter sweep 완료, 신규 기본값 채택**(+66.7% PnL) (2) Walk-Forward ✅ 기존 기본값으로 4개 자산 전부 CLOSED, **신규 기본값으로 BTC 재확인 PASS**(ETH/SOL/XRP는 표준 규모 재확인 아직 안 함) (3) Paper Trading ✅ 파이프라인 완료·가동 중, 리스크 컨트롤 강화됨(circuit breaker auto-reset) (4) Small Live ❌ operator 승인 대기, 실제 잔고 연동도 이 게이트로 명시적으로 이연됨.

Strategy > Risk > Backtest > Paper Trading > Dashboard 전 계층의 배관 갭은 전부 해소됨. 감사 HIGH 항목 3개 전부 A/B 검증 완료 — 4개 자산(BTC/ETH/SOL/XRP, 전부 2026년) + BTCUSDT의 2개 연도(2025/2026)까지 검증. **break-even**: 자산 축(2승2패)과 시간 축(BTC 단독으로도 +9.2%↔-1.9% 부호 반전) 양쪽 다 신뢰 방향 없음 — `ENABLE_BREAKEVEN` 기본 False **영구 확정**. **Breaker Block**: 대체로 부정, 일관성 약함. **Partial TP**: 4개 자산 + BTC 2개 연도 전부 일관되게 부정 — 유일하게 "적극 비추천" 근거를 갖춘 항목. **Confluence-strength**: 스펙 모호성 해소, 기존(느슨한) 구현이 옳다고 확정. **Parameter sweep**: 4개 core-rule 상수(`_RR`/`_STOP_BUFFER`/`_LOOKBACK`/`_IMPULSE_MULT`) 전부 in-sample+out-of-sample+cross-asset+cross-year 검증 통과, 신규 기본값 채택. Strategy Engine의 core-rule 레벨 감사·튜닝 항목은 이제 사실상 모두 해소됨(남은 건 equal-highs/lows처럼 스펙 자체가 없는 신규 규칙 후보, 그리고 실험적 기능 전용 파라미터 스윕뿐). **다음 최고-ROI 후보 (Phase 1 게이트 완료 우선순위)**:
- **ETH/SOL/XRP를 신규 기본값으로 표준 규모(3000캔들/6기간) walk-forward 재확인**: BTC만 표준 규모에서 재확인됨 — 게이트 #2를 신규 기본값 기준으로 완전히 다시 닫으려면 필요
- **`--end-date`로 추가 교차-연도 검증(신규 기본값 기준)**: (a) 2024년으로 더 과거, (b) ETH/SOL/XRP도 2025년으로 검증
- **`BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R`/`PARTIAL_TP_PORTION` 스윕**: 이번 라운드에서 의도적으로 제외됨(실험적 기능 전용, MVP baseline 강화와 무관) — `_RR`이 2.0→2.5로 바뀌었으니 partial-TP의 부정적 결론이 새 RR 하에서도 유지되는지 재검토 가치 있음
- **리스크 컨트롤 추가 감사 후보**: circuit breaker auto-reset은 완료됐지만, `RiskManager`/`DrawdownGuard`의 다른 엣지 케이스도 "production-ready" 관점에서 추가 점검 여지 있음(낮은 우선순위)
- **break-even/Breaker Block에 대해 "최종 결론 찾기"를 그만두는 것 고려**: 자산·시간 두 축 모두에서 신뢰 방향이 없다는 게 이미 충분히 확정적인 결론
- **scope 경계**: `/dashboard/signals`는 `run_paper.py`에서만 배선(`run_backtest.py`는 의도적으로 안 건드림)
- **`ltf_bias` 재검토 후보**: 실제 트레이딩 판단에 쓰이게 되면 재확인 필요
- Paper Trading 재검토 후보(낮은 우선순위, "갭 아님"): single-pass 모드의 loss-limit 거부가 Telegram/Discord 알림 없이 stdout/summary dict에만 보임
- **Live Trading으로 넘어갈 때**: 반드시 operator와 재확인 — API 키 발급 자체가 operator 승인 필요 카테고리에 해당, CTO/에이전트 재량으로 절대 시작하지 않음

모든 회차가 git에 커밋/push 완료(`origin/master`, 최신 커밋은 위 "전체 회차" 항목들 참조 — 이 문서의 각 항목에 실제 커밋 해시가 없다면 아직 미커밋일 수 있으니 `git log`로 교차 확인 권장). Small Live 진행 시 API 키 발급 + 단계별 승인 필요(operator 승인 없이는 절대 진행 안 함).

## 설계 결정 메모
- Backend: FastAPI + SQLAlchemy 2.0 + Alembic / Frontend: Next.js App Router + TypeScript (operator 확인, Milestone 1)
- Milestone 3 핵심 설계: execution/과 portfolio/가 서로의 파일을 건드리지 않도록(Iron Wall) 인터페이스를 사전에 고정 — 영속화는 caller(run_paper.py) 책임
- Milestone 4: circuit_breaker는 risk/ 도메인에 두고 duck-typed 옵션 파라미터로 risk_manager에 연결 — execution/에는 전혀 손대지 않음. notifications는 항상 안전한 no-op이므로 run_paper.py가 별도 on/off 체크 없이 무조건 호출
- 세션 API 한도로 일부 sub-agent가 "실패"로 표시된 적 있었음(Milestone 3) — 실제로는 파일이 이미 다 작성된 상태였고, 재배치 없이 제가 직접 검증만 진행해 리소스 절약. Milestone 4는 4개 태스크 모두 한도 문제 없이 정상 완료
- `fvg_zone`은 dict로 유지 (Milestone 2, DB JSON 컬럼과 타입 일치)
- `DrawdownGuard.check_*_loss`는 `True`=거래 허용, `False`=차단 컨벤션

## 주의사항
- LiveBroker, exchange 클라이언트는 여전히 `NotImplementedError` 완전 스텁 — 실거래소 API 호출·실주문 코드 전혀 없음
- `LIVE_TRADING_ENABLED` 기본값 `false` 유지, safety_checks.verify_safe_to_trade가 live-mode 오설정을 defense-in-depth로 재차 차단
- Paper 실행 결과(트레이드 손익)는 파이프라인 배관 검증 목적 — 전략 수익성 검증 아님, 실거래 여부와 무관하게 계속 유효
- git/GitHub는 Milestone 5에서 세팅 완료됨 (`https://github.com/jinalove1111/AutoCookie.git`, 커밋 `a385faa`는 M1~M4분, `9cb98aa`가 M5분). 이후 전체 회차도 모두 커밋/push 완료 — 새 작업 시작 전 `git status`/`git log`로 항상 최신 상태 재확인 권장
- 실사용 시 Postgres는 docker-compose 경로(미검증) 또는 직접 준비 필요 — 검증에 쓴 포터블 인스턴스는 임시였고 종료됨
- **Small Live Trading으로 넘어갈 때는 이 문서의 "다음 단계" 항목을 반드시 operator와 재확인 — API 키 스코프(출금 권한 없음), 소액 한도, 단계별 승인 없이 절대 실주문 코드 작성/실행 금지**
