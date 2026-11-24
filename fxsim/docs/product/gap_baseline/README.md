# 製品化ギャップの基準測定（2026-11-22）

`docs/PRODUCT_PROMPT.md`（製品化の指示書）の出発点として、6つの専門視点が現状を測った結果です。全63件（P0 24件）。視点ごとに1ファイルに分けてあります（本文は測定を行ったエージェントの報告で、英語です）。

## 読み方

- まずこのファイルの一覧と、各ファイル冒頭の **Summary** を読む。
- ある項目に着手する前に、その項目の **Evidence / Done / Risk to live** を全文読む。**Risk を読まずに着手しない。**
- **鵜呑みにしない。** 指示書のM0で、要点を自分の経路で測り直してから `BAR.md` に落とす。このフォルダは書き換えず、進捗は `BAR.md` に書く。
- 測定対象はコミット `40771f9`。証拠の `file:line` はこのコミットでの行番号。測定は読み取り専用で、リポジトリは変更していない。
- 再現に使ったスクリプトは `docs/product/baseline/`（走り書きの証拠。テストではない）。
- 優先度：P0＝製品と呼ぶ前に必須、P1＝重要、P2＝あるとよい。大きさ：S／M／L／XL。項目の番号は `視点名-番号`（例：`operations-1`）。

## この基準測定の、分かっている誤り

報告そのものは書き換えていない（測定の時点の記録である）。次の3点は、後の検証で誤りか、指示書と食い違うと分かった。指示書が優先する。

- 運用と設計の Summary が「週末に切り替える」を勧めている箇所がある。MT5かWindowsの再起動を伴う作業に週末は不適である（指示書の R6(e)）。
- 11/16の再生を「記録と一致（決済の試行16回）」としている箇所がある。一次記録は17回である（`../baseline/sre/logs_1116_anonymised.txt`）。
- `operations-4` が「MT5の自動起動」を安全な自己修復として挙げている。期限が切れた後のMT5の起動は、建玉の決済の引き金になる（合格基準のC5）。

## 一覧

### 1. [運用（自宅のWindows PCでの無人運転）](1-operations.md)

- `operations-1` [P0·L] The fail-safe closes a healthy position after a terminal-side outage (the 11-16 race is structural, not luck)
- `operations-2` [P0·M] Blind and idle states carry no cause; the health check misdiagnoses a terminal outage as a dead brain and prescribes the wrong remedy
- `operations-3` [P0·M] Nobody is told: no push channel, no dead-man switch, health check only on demand
- `operations-4` [P0·L] No boot chain and no preflight: nothing verifies the dozen dependencies after a reboot, and nothing runs natively on Windows to watch Docker itself
- `operations-5` [P1·L] A frozen feed is trusted for 75 hours on any weekday: a mid-week broker disconnect is invisible to the brain and the health check
- `operations-6` [P1·M] The broker stop is claimed but never observed; trade results are unchecked
- `operations-7` [P1·L] Updates are unsupervised and have no rollback; a reboot silently activates whatever is in the working tree
- `operations-8` [P1·M] State has no backup, and an unreadable database takes down the brain, the health check and the dashboard together
- `operations-9` [P1·M] No SLO and no incident ledger: 'minutes without a supervised position' is not measured, and self-healed incidents leave no trace

### 2. [検証（正しいとどう分かるか、間違いにどれだけ早く気づけるか）](2-verification.md)

- `verification-1` [P0·M] The resident loop's wiring of the historic fixes is not pinned by any test, and there is no coverage or mutation gate to show it
- `verification-2` [P0·XL] No deterministic closed-loop simulator: the REAL brain has never been run over the 11-year tape against an EA+broker model with I1-I12 checked on every step
- `verification-3` [P0·L] The EA is tested only through Python transcriptions; the MQL5 that places and closes orders has never been executed under any test
- `verification-4` [P0·M] The 2026-11-16 incident class (terminal not logged in after a reboot) has no scenario, no regression test and no line in the fault model; the fail-safe closes a healthy position by design when the cause clears
- `verification-5` [P0·M] No daily decision-parity check between the live account and the validated engine on the live tape; time-to-detect for a timing defect is months to years
- `verification-6` [P1·L] The brain's records are never reconciled with the broker's deal history; fills, slippage, swap and commission are unknown to the system
- `verification-7` [P1·M] Decision rows carry no order id and are written before the bridge write; there is no write-ahead intent journal and no crash-point testing
- `verification-8` [P1·L] No staging: a release goes from `git pull` straight to the live account, and nothing immutable identifies what is running
- `verification-9` [P1·M] What has never been verified on a real Windows + MT5 + Docker machine is listed in prose and stays unverified; there is no on-machine acceptance evidence
- `verification-10` [P2·M] Owner-facing numbers are hand-copied constants with no single source; parts of the evidence chain and of the health-check glue are outside CI

### 3. [所有者体験（非プログラマーの導入から復旧まで）](3-owner-experience.md)

- `owner-experience-1` [P0·L] The status instruments name the wrong cause and the wrong next step, and cannot say 'operating normally'
- `owner-experience-2` [P0·M] Nothing reaches the owner unless they look: no notification, no dead-man's switch, no morning digest
- `owner-experience-3` [P0·XL] No installer and no first-run check: about 30 manual steps in four files, 8 undocumented prerequisites, silent failure on a wrong path
- `owner-experience-4` [P1·L] Dashboard is a developer page: dead and false cards, no position detail, tiny grey status, stale-green on failure, paper-simulator front page
- `owner-experience-5` [P1·M] No memory of incidents: after recovery every instrument reads normal and the outage is invisible
- `owner-experience-6` [P1·M] No self-diagnosis bundle: an incident is investigated by the owner pasting whatever the developer asks for
- `owner-experience-7` [P1·L] Updating depends on the developer's notice: manual restart-or-rebuild choice, log-grep verification, no versions, no rollback
- `owner-experience-8` [P1·M] Three generations of documents; 'current' ones contain obsolete and unsafe instructions and disagree with the code
- `owner-experience-9` [P1·M] Deposits, withdrawals, year-end and backup are not product flows
- `owner-experience-10` [P1·S] The honest expectation is not shown where the owner decides (phone, deposit, drawdown, leverage dial)
- `owner-experience-11` [P2·S] The on-chart EA line is English, omits login/trading state, and is easy to misread

### 4. [研究の誠実さ（戦略の根拠）](4-research-integrity.md)

- `research-integrity-1` [P0·L] No forward (live) performance attribution: the real-money record has never been reconciled with the rule it is supposed to run
- `research-integrity-2` [P0·L] Published numbers cannot all be regenerated from a clean checkout, and owner-facing tools still carry superseded or unbacked figures
- `research-integrity-3` [P0·M] Nothing mechanical stops a future developer (or the user's .env) from 'improving' the return by searching parameters
- `research-integrity-4` [P1·M] The trial ledger and the pre-registrations exist only as prose with inconsistent counts
- `research-integrity-5` [P1·M] Research data has no provenance record, no checksums, no licence, and an unnamed source for the tape every H1 number rests on
- `research-integrity-6` [P1·M] The edge's statistical significance was measured on the lucky path and never restated; selection of the SMA length was never corrected for
- `research-integrity-7` [P1·M] There is no independent data on which the production rule, or the lottery, has ever been observed at H1
- `research-integrity-8` [P1·L] The chain 'backtest = harness = what the monitor expects = what the brain does' has links that are true today but not pinned, and one that is only modelled
- `research-integrity-9` [P2·L] The entry-size lottery is open, but the harness cannot evaluate candidates at the account's operating point and no bounded study programme exists
- `research-integrity-10` [P2·S] Assumed inputs behind the claims are never compared with measured ones, and the comparison the owner actually faces is missing

### 5. [設計（何年も保守して出していける形か）](5-architecture.md)

- `architecture-1` [P0·M] No golden-trace replay harness around the unmodified live loop (prerequisite for every other change)
- `architecture-2` [P0·S] No shadow mode: a candidate brain cannot run beside the live one, so nothing can be verified on the real machine before it trades
- `architecture-3` [P1·L] The resident loop is a 526-line function with 27 untyped loop-carried variables; there is no explicit state machine shared with the simulator
- `architecture-4` [P0·L] The Python-MQL5 protocol is specified only in comments (some false), and the EA has no executable test
- `architecture-5` [P0·M] No durable structured event log and no correlation from decision to order to fill; incident evidence is erased by the update procedure
- `architecture-6` [P1·M] Configuration has no single schema: documented dials that do nothing, working dials that are undocumented, misspellings accepted silently
- `architecture-7` [P1·M] No releases: the running code is whatever the working tree held at the last process start
- `architecture-8` [P1·M] Durable state is a patchwork recovered from a log table; the database has no schema version, migration path, backup or integrity check
- `architecture-9` [P1·M] Legacy, experiment and stock-trading code ships in the same tree and is not inert
- `architecture-10` [P1·M] The strategy's rules exist in several independent implementations; 'live behaves like the backtest' rests on a transcription
- `architecture-11` [P0·S] Guardrail: refactors that look like improvements and are not worth their risk on this live system

### 6. [セキュリティと配布](6-security-compliance.md)

- `security-compliance-1` [P0·L] The EA has no safety limit of its own: no hard maximum lot, no mandatory stop, expiry or id, no price or account-state sanity check, no kill switch
- `security-compliance-2` [P0·M] The order channel is an unauthenticated file writable by many parties, and the internet-facing container is one of them
- `security-compliance-3` [P0·M] Dashboard authentication fails open, and parts of it are reachable without credentials
- `security-compliance-4` [P1·M] Dashboard input and output handling: unescaped model text, path-taking POST, writes into the live database
- `security-compliance-5` [P1·M] Secret and personal-data hygiene: keys in object repr, every secret in every container, personal identifiers in the docs, undeclared data flow to the AI provider
- `security-compliance-6` [P1·M] Supply chain: floating images and actions, no hashes, no vulnerability scan, no component inventory
- `security-compliance-7` [P1·M] Change management and release identity: live runs whatever the head of a working branch is
- `security-compliance-8` [P1·M] Record keeping: no order or fill journal, and operational logs die with the container
- `security-compliance-9` [P1·M] Licence and intellectual-property position is undefined, and bundled market data has no provenance
- `security-compliance-10` [P0·L] No distribution-readiness pack: no acknowledged risk disclosure, no terms, no rule for how performance figures are presented, no professional review gate
- `security-compliance-11` [P1·S] Security has no invariant, no ledger column, no reporting channel and no scheduled review
- `security-compliance-12` [P2·M] Legacy and unrelated code ships inside the product and widens the attack surface

