# HANDOFF — JadeCap Automated Trading Bot

## 상태: 페이퍼 트레이드가 SL/TP 도달 시 실제로 청산되지 않던 문제 해소 — 이제 매 pass마다 오픈 포지션을 실제로 체크/청산하고 PnL을 기록함. 실 체결가(슬리피지 반영)가 진입가로 기록되도록 수정. Live 관련 코드는 여전히 전무 — Small Live는 operator의 명시적 승인 대기 중

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
Paper Mode 파이프라인이 이제 end-to-end로 실제로 동작함: Strategy Engine(HTF/LTF 실분리 + confluence 방향 일치) → Risk Engine(실 daily/weekly loss-limit 집행 + 실 RISK_PER_TRADE_PERCENT 사이징, Backtest/Paper 공용) → Execution(실 체결가/수수료 노출) → 포지션이 실제로 열리고 SL/TP 도달 시 실제로 닫히며 실 fill price 기준 PnL이 기록됨 → circuit breaker가 그 실현 손실을 실제로 볼 수 있음. 모든 회차가 git에 커밋/push 완료(`origin/master`, 최신 커밋은 위 "전체 회차" 항목들 참조 — 이 문서의 각 항목에 실제 커밋 해시가 없다면 아직 미커밋일 수 있으니 `git log`로 교차 확인 권장). 다음 후보(우선순위: Strategy > Risk > Backtest > Paper Trading > Dashboard > Live): 대시보드의 `BiasCard`/`SignalsPanel`/`RiskStatusPanel`이 여전히 하드코딩 placeholder(`get_market_bias`/`get_recent_signals`/`get_risk_status` 백엔드 엔드포인트 자체가 아직 실전략 상태로 안 이어짐). Small Live 진행 시 API 키 발급 + 단계별 승인 필요(operator 승인 없이는 절대 진행 안 함).

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
