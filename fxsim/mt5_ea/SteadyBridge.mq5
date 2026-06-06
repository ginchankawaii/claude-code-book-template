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
//|     steady_signal.txt  (Python -> EA)  "LONG <lots>" | "FLAT 0" |
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

CTrade trade;

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   EventSetTimer(InpTimerSec);
   ExportAll();
   ProcessSignal();
   Print("SteadyBridge started on ", InpSymbol);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { ExportAll(); ProcessSignal(); }
void OnTick()  { /* timer drives everything */ }

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
      FileWrite(hs,
         DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2),
         DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2),
         DoubleToString(CurrentLots(), 2));
      FileClose(hs);
   }
}

double NormalizeLots(double lots)
{
   double step = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   lots = MathFloor(lots / step) * step;
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

//--- read + act on the Python signal -------------------------------
//  signal: "LONG <lots>" | "SHORT <lots>" | "FLAT 0"
//  Tracks the AI's target size: opens, flips, and RESIZES an open position
//  (add / partial-close) toward the target, with a deadband to avoid churn.
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
   double lots = (k >= 2) ? NormalizeLots(StringToDouble(parts[1])) : 0.0;

   double target = 0.0;                       // signed target
   if(action == "LONG")  target = lots;
   else if(action == "SHORT") target = -lots;

   double cur = CurrentLots();                // signed: + long / - short

   // 1) FLAT -> close everything
   if(target == 0.0) { if(MathAbs(cur) > 0) CloseAll(); return; }
   // 2) opposite sign -> flip: close now, reopen on next tick
   if(cur != 0.0 && (cur > 0) != (target > 0)) { CloseAll(); return; }
   // 3) flat -> open fresh in the target direction
   if(cur == 0.0)
   {
      if(target > 0) trade.Buy(MathAbs(target), InpSymbol);
      else           trade.Sell(MathAbs(target), InpSymbol);
      return;
   }
   // 4) same direction -> resize toward target if outside the deadband
   double cur_abs = MathAbs(cur), tgt_abs = MathAbs(target);
   double diff = tgt_abs - cur_abs;
   double band = MathMax(InpResizeMinLots, cur_abs * InpResizePct);
   if(MathAbs(diff) < band) return;           // close enough -> hold (no churn)
   if(diff > 0)
   {
      double add = NormalizeLots(diff);
      if(add > 0) { if(target > 0) trade.Buy(add, InpSymbol); else trade.Sell(add, InpSymbol); }
   }
   else
   {
      ReduceBy(NormalizeLots(-diff));          // trim toward target
   }
}
//+------------------------------------------------------------------+
