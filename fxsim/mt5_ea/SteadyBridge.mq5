//+------------------------------------------------------------------+
//|   SteadyBridge.mq5                                               |
//|   File-bridge EA for the Python "Steady" system.                |
//|                                                                  |
//|   Exports recent bars (default H1) + account status to shared   |
//|   Common\Files folder, and executes the order signal the Python |
//|   brain writes there. Long-or-flat only. Bypasses the (broken)  |
//|   MetaTrader5 Python IPC entirely.                              |
//|                                                                  |
//|   Files (in Common\Files):                                      |
//|     steady_bars.csv    (EA -> Python)  time,open,high,low,close |
//|     steady_status.csv  (EA -> Python)  balance,equity,pos_lots  |
//|     steady_signal.txt  (Python -> EA)                          |
//|       "LONG <lots> [SEQ <n>] [EXP <unix>] [SL <price>]"          |
//|       | "FLAT 0 [SEQ <n>] [EXP <unix>]"                          |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

input string         InpSymbol    = "USDJPY";     // exact Market Watch symbol
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_H1;   // bar timeframe to export (H1 = recommended)
input int            InpBars      = 2500;         // bars to export (>= trend SMA + buffer; H1/SMA2400 needs >=2405)
input long           InpMagic     = 770077;       // our orders' magic number
input int    InpTimerSec   = 30;         // export/check interval
input string InpBarsFile   = "steady_bars.csv";
input string InpStatusFile = "steady_status.csv";
input string InpSignalFile = "steady_signal.txt";
input double InpResizeMinLots = 0.10;    // resize open pos only if lot diff >= this ...
input double InpResizePct     = 0.20;    // ... or >= this fraction of current size (deadband)

// Bumped whenever the EA's execution behaviour changes, so the operator can
// tell a recompiled EA from a stale one at a glance — the input dialog cannot.
#define EA_BUILD "r5-seqgate"

CTrade trade;
datetime g_expiry = 0;   // last EXP token seen on the signal (0 = heartbeat-less)

//--- execution-sequence gate (round-5, CRITICAL) --------------------
//  steady_signal.txt is a STANDING target that this EA re-executes on
//  every timer tick, with no memory of having acted. Round-4 added a
//  real broker SL that closes the position server-side — so the moment
//  the stop filled, the still-standing "LONG <lots>" line made the very
//  next tick (<=30s) re-buy the same size: no decision, no trend check,
//  and — its stop now being at/through the market — NO stop. The same
//  hole silently undid the operator's own manual closes within 30s.
//
//  Rule: the EA may ALWAYS reduce or close (the safe direction), but may
//  only OPEN or INCREASE when the brain issues a NEW order, i.e. when the
//  SEQ token changes. Heartbeats repeat SEQ, so they only maintain the
//  broker stop and the expiry — they can never re-open a closed position.
//  The executed SEQ is persisted in a terminal GlobalVariable so a restart
//  of MT5 does not re-open a position that was closed while it was down.
long   g_exec_seq  = 0;    // last SEQ we opened/increased on
string g_exec_key  = "";   // same, for unsequenced (manual/legacy) signals
bool   g_held_flat = false;// warned once about holding flat on a heartbeat

string SeqGvName() { return "SteadyBridge_seq_" + InpSymbol + "_" + (string)InpMagic; }

//  A new order is one we have not executed. SEQ is authoritative; an
//  unsequenced signal (hand-written file, pre-round-5 brain) falls back to
//  the line content with the ever-changing EXP token removed.
bool IsNewOrder(long seq, string key)
{
   if(seq > 0) return seq != g_exec_seq;
   return key != g_exec_key;
}

void CommitExec(long seq, string key)
{
   g_exec_key = key;
   if(seq > 0) { g_exec_seq = seq; GlobalVariableSet(SeqGvName(), (double)seq); }
}

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   if(GlobalVariableCheck(SeqGvName()))
      g_exec_seq = (long)GlobalVariableGet(SeqGvName());
   EventSetTimer(InpTimerSec);
   ExportAll();
   ProcessSignal();
   UpdateStatusComment();
   Print("SteadyBridge started on ", InpSymbol, " | build ", EA_BUILD,
         " | last executed order SEQ ", g_exec_seq);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); Comment(""); }
void OnTimer() { ExportAll(); ProcessSignal(); UpdateStatusComment(); }
void OnTick()  { /* timer drives everything */ }

//--- always-visible chart status: is the Python brain alive? ---------
//  The brain heartbeats the signal file with an EXP token every poll
//  tick; if Docker/PC dies, this line is how the operator notices.
void UpdateStatusComment()
{
   string hb;
   if(g_expiry == 0)
      hb = "no heartbeat token (old brain / manual signal)";
   else if(TimeGMT() > g_expiry)
      hb = StringFormat("!! BRAIN SILENT — signal expired %d min ago !!",
                        (int)((TimeGMT() - g_expiry) / 60));
   else
      hb = StringFormat("brain OK (heartbeat valid %d more min)",
                        (int)((g_expiry - TimeGMT()) / 60));
   Comment("SteadyBridge ", EA_BUILD, " | pos ", DoubleToString(CurrentLots(), 2),
           " lots | ", hb);
}

//--- net lots of OUR positions (long +, short -) -------------------
double CurrentLots()
{
   double net = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk))
      {
         if(PositionGetString(POSITION_SYMBOL) == InpSymbol &&
            PositionGetInteger(POSITION_MAGIC) == InpMagic)
         {
            double v = PositionGetDouble(POSITION_VOLUME);
            if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL) v = -v;
            net += v;
         }
      }
   }
   return net;
}

//--- export bars + account status ----------------------------------
void ExportAll()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(InpSymbol, InpTimeframe, 0, InpBars, r);
   if(n > 0)
   {
      int h = FileOpen(InpBarsFile, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
      if(h != INVALID_HANDLE)
      {
         FileWrite(h, "time", "open", "high", "low", "close");
         for(int i = n - 1; i >= 0; i--)   // oldest -> newest
            FileWrite(h,
               TimeToString(r[i].time, TIME_DATE|TIME_SECONDS),
               DoubleToString(r[i].open, 5), DoubleToString(r[i].high, 5),
               DoubleToString(r[i].low, 5),  DoubleToString(r[i].close, 5));
         FileClose(h);
      }
   }
   int hs = FileOpen(InpStatusFile, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(hs != INVALID_HANDLE)
   {
      FileWrite(hs, "balance", "equity", "position_lots");
      // 3 decimals: at 2dp a dust residue (e.g. 0.004 lots after a partial
      // close) is invisible to the brain, which then loops paid entry
      // decisions forever against a book it cannot see (round-4 audit).
      FileWrite(hs,
         DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2),
         DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2),
         DoubleToString(CurrentLots(), 3));
      FileClose(hs);
   }
}

double NormalizeLots(double lots)
{
   double step = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   // +epsilon before flooring: 0.29/0.01 = 28.999999999999996 in doubles,
   // and a bare floor silently drops a whole lot step on ~12% of exact
   // brain targets (final-fuzz property test).
   lots = MathFloor(lots / step + 0.0000001) * step;
   if(lots < vmin) lots = 0.0;
   if(lots > vmax) lots = vmax;
   return lots;
}

void CloseAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk))
         if(PositionGetString(POSITION_SYMBOL) == InpSymbol &&
            PositionGetInteger(POSITION_MAGIC) == InpMagic)
            trade.PositionClose(tk);
   }
}

// reduce our net exposure by `vol` lots (partial/full closes across tickets)
void ReduceBy(double vol)
{
   for(int i = PositionsTotal() - 1; i >= 0 && vol > 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL) != InpSymbol ||
         PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      double pv = PositionGetDouble(POSITION_VOLUME);
      double cv = NormalizeLots(MathMin(pv, vol));
      if(cv <= 0) continue;
      if(cv >= pv) trade.PositionClose(tk);
      else         trade.PositionClosePartial(tk, cv);
      vol -= cv;
   }
}

//--- broker-side protective stop (round-4) -------------------------
//  The brain sends its 1.5-ATR stop as "SL <price>"; mirroring it as a
//  real broker SL protects through brain outages and fills AT the stop
//  instead of the next poll's close (audit: ~3.4pp CAGR of poll-stop
//  slippage recovered for ~0.05% gap cost). Longs only.
double ValidLongSL(double sl)
{
   if(sl <= 0) return 0.0;
   double bid   = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   long   stops = SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL);
   if(bid <= 0 || point <= 0) return 0.0;
   if(sl >= bid - (stops + 1) * point) return 0.0;   // too close/above: skip,
                                                     // the brain still guards
   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   return NormalizeDouble(sl, digits);
}

void ApplyStopLoss(double sl_px, double cur)
{
   if(cur <= 0 || sl_px <= 0) return;                // our longs only
   double sl = ValidLongSL(sl_px);
   if(sl <= 0) return;
   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL) != InpSymbol ||
         PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY) continue;
      double cur_sl = PositionGetDouble(POSITION_SL);
      if(cur_sl <= 0 || MathAbs(cur_sl - sl) > 2 * point)
         trade.PositionModify(tk, sl, PositionGetDouble(POSITION_TP));
   }
}

//--- read + act on the Python signal -------------------------------
//  signal: "LONG <lots>" | "FLAT 0"  [+ " SEQ <n>" " EXP <unix>" " SL <px>"]
//  Tracks the brain's target size: opens, flips, and RESIZES an open position
//  (add / partial-close) toward the target, with a deadband to avoid churn.
//  Opening and increasing require a NEW order (changed SEQ); reducing and
//  closing are always permitted. See the round-5 note on the sequence gate.
void ProcessSignal()
{
   if(!FileIsExist(InpSignalFile, FILE_COMMON)) return;
   int h = FileOpen(InpSignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE) return;
   string line = FileReadString(h);
   FileClose(h);

   string parts[];
   int k = StringSplit(line, ' ', parts);
   if(k < 1) return;
   string action = parts[0];
   double lots_raw = (k >= 2) ? StringToDouble(parts[1]) : 0.0;
   double lots = NormalizeLots(lots_raw);
   // Loud warning when the broker's lot spec silently kills the order: a
   // volume-min/step above the brain's target (e.g. min 0.10 vs target 0.09)
   // floors it to zero and the system would trade nothing forever (round-4).
   if(action == "LONG" && lots_raw > 0 && lots <= 0)
      Print("SteadyBridge: target ", DoubleToString(lots_raw, 3),
            " lots is below this broker's volume min/step (min=",
            DoubleToString(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN), 2),
            " step=", DoubleToString(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP), 2),
            ") -> order suppressed. Fix sizing or broker.");

   // Optional tokens after "<ACTION> <lots>":
   //   EXP <unix-utc> : heartbeat expiry -> FLAT fail-safe when the brain dies
   //                    or goes blind (it stops refreshing on a dead feed).
   //   SL <price>     : the brain's protective stop, mirrored as a REAL broker
   //                    SL so protection survives brain outages and fills at
   //                    the stop price instead of the next poll's close.
   long   expiry = 0;
   double sl_px  = 0.0;
   long   seq    = 0;
   for(int i = 2; i + 1 < k; i += 2)
   {
      if(parts[i] == "EXP")      expiry = StringToInteger(parts[i + 1]);
      else if(parts[i] == "SL")  sl_px  = StringToDouble(parts[i + 1]);
      else if(parts[i] == "SEQ") seq    = StringToInteger(parts[i + 1]);
   }
   // Order identity for the open/increase gate: everything that defines the
   // order, with the per-heartbeat EXP deliberately excluded.
   string order_key = action + " " + DoubleToString(lots_raw, 3) + " SL "
                    + DoubleToString(sl_px, 5);
   g_expiry = (datetime)expiry;                // chart status (UpdateStatusComment)
   if(expiry > 0 && (long)TimeGMT() > expiry)
   {
      if(MathAbs(CurrentLots()) > 0)
      {
         Print("SteadyBridge: signal expired (brain heartbeat lost) -> FLAT fail-safe");
         CloseAll();
      }
      return;
   }

   double target = 0.0;                       // signed target
   if(action == "LONG")  target = lots;
   else if(action == "SHORT")
   {
      // Long-or-flat system: a SHORT line can only come from a manual edit or
      // a foreign writer. Never sell — treat as FLAT and say so (round-4).
      Print("SteadyBridge: SHORT signal refused (long-or-flat system) -> treating as FLAT");
      target = 0.0;
   }

   double cur = CurrentLots();                // signed: + long / - short
   ApplyStopLoss(sl_px, cur);

   // 1) FLAT -> close everything. Closing is the safe direction and is never
   //    gated: an expired or flat signal must always be able to flatten.
   if(target == 0.0) { if(MathAbs(cur) > 0) CloseAll(); return; }
   // 2) opposite sign -> flip: close now, reopen on next tick
   if(cur != 0.0 && (cur > 0) != (target > 0)) { CloseAll(); return; }
   // 3) flat -> open, but ONLY on a new order. A repeated SEQ means the brain
   //    is heartbeating an order it already placed; if the book is empty the
   //    position was closed by the broker stop, the EXP fail-safe or the
   //    operator, and re-buying it here would undo exactly that (round-5).
   if(cur == 0.0)
   {
      if(target <= 0) return;                   // long-or-flat: never sell
      if(!IsNewOrder(seq, order_key))
      {
         if(!g_held_flat)
            Print("SteadyBridge: flat, but this signal is a HEARTBEAT of order ",
                  seq, " which was already executed -> NOT re-opening. The "
                  "position was closed by the stop, the fail-safe or you; the "
                  "brain must decide again before any new entry.");
         g_held_flat = true;
         return;
      }
      g_held_flat = false;
      if(trade.Buy(MathAbs(target), InpSymbol, 0.0, ValidLongSL(sl_px), 0.0))
         CommitExec(seq, order_key);
      return;
   }
   g_held_flat = false;
   // 4) same direction -> resize toward target if outside the deadband.
   //    A dust book (below the deadband floor itself) must always converge:
   //    the round-4 audit wedged the state at 0.004 lots forever otherwise.
   double cur_abs = MathAbs(cur), tgt_abs = MathAbs(target);
   double diff = tgt_abs - cur_abs;
   double band = MathMax(InpResizeMinLots, cur_abs * InpResizePct);
   if(cur_abs < InpResizeMinLots) band = 0;   // dust: no deadband, converge
   if(MathAbs(diff) < band) return;           // close enough -> hold (no churn)
   if(diff > 0)
   {
      // Increasing is the risk-adding direction, so it needs a new order too:
      // a partial external close (partial stop fill, manual trim) must not be
      // silently refilled by a heartbeat. The brain re-decides instead.
      if(!IsNewOrder(seq, order_key))
      {
         Print("SteadyBridge: book ", DoubleToString(cur_abs, 2), " is under target ",
               DoubleToString(tgt_abs, 2), " but this signal is a HEARTBEAT of order ",
               seq, " -> not adding. Part of the position was closed outside the "
               "brain; it will reconcile and decide.");
         return;
      }
      double add = NormalizeLots(diff);
      if(add > 0 && target > 0 && trade.Buy(add, InpSymbol))
         CommitExec(seq, order_key);
   }
   else
   {
      ReduceBy(NormalizeLots(-diff));          // trim toward target: always allowed
   }
}
//+------------------------------------------------------------------+
