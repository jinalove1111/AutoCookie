# HANDOFF — JadeCap Automated Trading Bot

## 상태: 백테스트 엔진 HTF/LTF 워크포워드 블로커 해소 완료. Live 관련 코드는 여전히 전무 — Small Live는 operator의 명시적 승인 대기 중

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
Milestone 5 전체 완료 + 오케스트레이터 직접 실제 Postgres 검증 통과. git/GitHub 세팅 + Alembic 마이그레이션까지 완료되어 Paper Mode가 인프라적으로도 완결. Milestone 5 변경분 커밋/push는 아직 안 함 — 다음 요청 대기 중 (Small Live 진행 시 API 키 발급 + 단계별 승인 필요).

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
- git/GitHub는 Milestone 5에서 완료됨 (`https://github.com/jinalove1111/AutoCookie.git`, 커밋 `a385faa`는 M1~M4분). M5 변경분(Alembic 등)은 아직 미커밋 — 다음 작업 전 커밋 권장
- 실사용 시 Postgres는 docker-compose 경로(미검증) 또는 직접 준비 필요 — 검증에 쓴 포터블 인스턴스는 임시였고 종료됨
- **Small Live Trading으로 넘어갈 때는 이 문서의 "다음 단계" 항목을 반드시 operator와 재확인 — API 키 스코프(출금 권한 없음), 소액 한도, 단계별 승인 없이 절대 실주문 코드 작성/실행 금지**
