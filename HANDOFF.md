# HANDOFF — JadeCap Automated Trading Bot

## 상태: Milestone 7 (ModeToggle 실전환 액션) 완료. Live 관련 코드는 여전히 전무 — Small Live는 operator의 명시적 승인 대기 중

## 전체 회차
- [x] Milestone 7 — `portfolio/positions.py`에 `update_bot_mode(mode)` 추가 — `BotState.mode` 실제 영속화
- [x] Milestone 7 — `GET /settings/mode`가 이제 DB(`BotState`)에서 읽어 `/dashboard/status`와 항상 일치 (기존엔 env값을 읽어 두 엔드포인트가 다를 수 있던 불일치 수정)
- [x] Milestone 7 — `POST /settings/mode`: paper/backtest는 실제 DB 저장 후 `{"trading_mode":..., "applied":true}` 반환, 유효하지 않은 값은 400. **live 분기는 문자 하나도 안 건드림** — 조건/상태코드/메시지 그대로 유지
- [x] Milestone 7 — `frontend/lib/api.ts`에 `setTradingMode()` 추가 (POST, FastAPI `detail` 필드 파싱해 명확한 에러 표시). `ModeToggle.tsx`가 실제 backtest/paper/live 버튼으로 전환 — live 시도 시 403 메시지를 숨기지 않고 그대로 노출(안전장치가 작동하는 걸 보여주는 것이 목적)
- [x] Milestone 7 — 오케스트레이터(저) 독립 재검증: 실제 백엔드 기동 → `/settings/mode`·`/dashboard/status` 초기 일치 확인 → backtest 전환(200, 영속화 확인) → **live 시도(403, DB `updated_at` 불변 확인)** → 잘못된 값(400) → paper 복귀(200) → `tsc --noEmit`/`npm run build`/backend `py_compile` 전부 제가 직접 재실행해 클린 통과 → 테스트 서버 종료, 임시 DB 삭제
- [ ] Milestone 7 변경사항은 아직 git에 커밋되지 않음 — 마지막 push는 Milestone 6(`5a9ff47`)까지
- [ ] **frontend sub-agent가 발견한 인프라 gap**: 앱 시작 시 자동으로 스키마를 만드는 부트스트랩이 없음 (`main.py`에 `create_all()`/migration 자동 실행 없음) — 완전히 새 DB에 처음 `/settings/mode`나 `/dashboard/status`를 호출하면 500 발생. 지금까지는 검증할 때마다 수동으로 `create_all()`을 먼저 돌려서 안 드러났음. 실배포 전 `alembic upgrade head`를 앱 시작 절차에 넣거나 문서화 필요

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
- [ ] frontend는 아직 이 실DB 엔드포인트들을 소비하지 않음 (Milestone 1 스캐폴딩 상태 그대로)
- [ ] CircuitBreaker 상태는 프로세스 메모리에만 존재 — 재시작하면 초기화됨 (DB 영속화는 다음 단계 후보)

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
