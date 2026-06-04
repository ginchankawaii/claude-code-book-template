//+------------------------------------------------------------------+
//|   SteadyBridge.mq5                                               |
//|   File-bridge EA for the Python "Steady" system.                |
//|                                                                  |
//|   Exports recent daily bars + account status to MT5's shared    |
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

input string InpSymbol     = "USDJPY";   // exact Market Watch symbol
input int    InpBars       = 260;        // daily bars to export
input long   InpMagic      = 770077;     // our orders' magic number
input int    InpTimerSec   = 30;         // export/check interval
input string InpBarsFile   = "steady_bars.csv";
input string InpStatusFile = "steady_status.csv";
input string InpSignalFile = "steady_signal.txt";

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
   int n = CopyRates(InpSymbol, PERIOD_D1, 0, InpBars, r);
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

//--- read + act on the Python signal -------------------------------
//  signal: "LONG <lots>" | "SHORT <lots>" | "FLAT 0"
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
   double lots = (k >= 2) ? StringToDouble(parts[1]) : 0.0;
   lots = NormalizeLots(lots);

   double cur = CurrentLots();   // signed: + long / - short

   if(action == "FLAT")
   {
      if(MathAbs(cur) > 0) CloseAll();
   }
   else if(action == "LONG")
   {
      if(cur < 0) { CloseAll(); return; }        // flip: close short first
      if(cur == 0 && lots > 0) trade.Buy(lots, InpSymbol);
   }
   else if(action == "SHORT")
   {
      if(cur > 0) { CloseAll(); return; }         // flip: close long first
      if(cur == 0 && lots > 0) trade.Sell(lots, InpSymbol);
   }
}
//+------------------------------------------------------------------+
