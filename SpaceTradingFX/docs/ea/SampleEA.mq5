//+------------------------------------------------------------------+
//| SampleEA.mq5 - EMA Crossover with License Activation             |
//| Demonstrates calling your Flask activation API                   |
//+------------------------------------------------------------------+
#property copyright "SpaceTradingFX"
#property version   "1.0"
#property strict

input string LicenseKey      = "PUT-YOUR-LICENSE-KEY-HERE"; // Provided after purchase
input int    FastEMAPeriod    = 12;
input int    SlowEMAPeriod    = 26;
input double Lots             = 0.10;
input bool   AllowTrading     = true;
input int    RecheckHours     = 24;  // Periodic license re-check

// Activation / licensing state
bool   g_LicenseOK       = false;
string g_LastError       = "";
datetime g_LastCheck     = 0;
string g_AccountNumber   = "";
string g_ServerName      = "";

// WebRequest endpoint (must be added in MT5: Tools->Options->Expert Advisors)
string ACTIVATION_URL    = "https://your-domain.com/api/license/activate";
string STATUS_URL        = "https://your-domain.com/api/license/status";

//+------------------------------------------------------------------+
//| Utility: Perform POST WebRequest                                 |
//+------------------------------------------------------------------+
string HttpPost(string url, string json)
{
   char   result[];
   char   post[];
   string headers = "Content-Type: application/json";
   int timeout = 10000;
   int res = WebRequest("POST", url, "application/json", headers, timeout, json, post, result);
   if(res == 200)
      return CharArrayToString(result);
   return "";
}

//+------------------------------------------------------------------+
//| Utility: Perform GET WebRequest                                  |
//+------------------------------------------------------------------+
string HttpGet(string url)
{
   char   result[];
   char   post[];
   string headers = "";
   int timeout = 8000;
   int res = WebRequest("GET", url, "application/json", headers, timeout, "", post, result);
   if(res == 200)
      return CharArrayToString(result);
   return "";
}

//+------------------------------------------------------------------+
//| Attempt license activation                                       |
//+------------------------------------------------------------------+
bool ActivateLicense()
{
   g_AccountNumber = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   g_ServerName    = AccountInfoString(ACCOUNT_SERVER);
   string machine  = TerminalInfoString(TERMINAL_DATA_PATH); // simplistic fingerprint
   string payload  = "{\"license_key\":\"" + LicenseKey + "\",\"account_number\":\"" + g_AccountNumber + "\",\"server\":\"" + g_ServerName + "\",\"machine_fingerprint\":\"" + machine + "\"}";
   string resp     = HttpPost(ACTIVATION_URL, payload);
   if(resp == "") { g_LastError = "No response"; return false; }
   // Very light parsing (for demo). In production parse JSON robustly.
   if(StringFind(resp, "\"ok\":true") != -1) {
      g_LicenseOK = true;
      g_LastCheck = TimeCurrent();
      return true;
   }
   g_LastError = resp;
   return false;
}

//+------------------------------------------------------------------+
//| Periodic license status check                                    |
//+------------------------------------------------------------------+
bool CheckLicenseStatus()
{
   if(!g_LicenseOK) return false;
   if((TimeCurrent() - g_LastCheck) < RecheckHours * 3600) return g_LicenseOK; // skip until interval
   string url  = STATUS_URL + "?license_key=" + LicenseKey;
   string resp = HttpGet(url);
   if(resp == "") { g_LastError = "Empty status"; return g_LicenseOK; }
   if(StringFind(resp, "\"ok\":true") != -1 && StringFind(resp, "\"status\":\"active\"") != -1) {
      g_LicenseOK = true;
      g_LastCheck = TimeCurrent();
      return true;
   }
   // On failure: provide short grace (EA keeps running this session but no new trades)
   g_LicenseOK = false;
   g_LastError = resp;
   return false;
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   if(!ActivateLicense()) {
      Print("[License] Activation failed: ", g_LastError);
      // Allow a trial fallback: user can observe but trading disabled
      g_LicenseOK = false;
   } else {
      Print("[License] Activation success for account ", g_AccountNumber);
   }
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Compute EMAs                                                      |
//+------------------------------------------------------------------+
void GetEMAs(int fastPeriod, int slowPeriod, double &fast, double &slow)
{
   fast = iMA(_Symbol, PERIOD_CURRENT, fastPeriod, 0, MODE_EMA, PRICE_CLOSE, 0);
   slow = iMA(_Symbol, PERIOD_CURRENT, slowPeriod, 0, MODE_EMA, PRICE_CLOSE, 0);
}

//+------------------------------------------------------------------+
//| Trade signal                                                      |
//+------------------------------------------------------------------+
int GetSignal()
{
   double f, s; GetEMAs(FastEMAPeriod, SlowEMAPeriod, f, s);
   double fPrev = iMA(_Symbol, PERIOD_CURRENT, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double sPrev = iMA(_Symbol, PERIOD_CURRENT, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   if(f > s && fPrev <= sPrev) return 1;  // Bullish crossover
   if(f < s && fPrev >= sPrev) return -1; // Bearish crossover
   return 0;
}

//+------------------------------------------------------------------+
//| Open trade helper                                                 |
//+------------------------------------------------------------------+
bool OpenTrade(int direction)
{
   if(!AllowTrading || !g_LicenseOK) return false;
   double price = (direction == 1) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl=0, tp=0; // Add risk management logic
   ENUM_ORDER_TYPE type = (direction == 1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   MqlTradeRequest req; MqlTradeResult res; ZeroMemory(req); ZeroMemory(res);
   req.action   = TRADE_ACTION_DEAL;
   req.symbol   = _Symbol;
   req.type     = type;
   req.volume   = Lots;
   req.price    = price;
   req.sl       = sl; req.tp = tp;
   req.deviation= 10;
   req.type_filling = ORDER_FILLING_FOK;
   if(!OrderSend(req, res)) {
      Print("OrderSend failed: ", res.retcode);
      return false;
   }
   Print("Opened ", (direction==1 ? "BUY" : "SELL"), " ticket ", res.order, " at ", price);
   return true;
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   // Periodic license re-check
   CheckLicenseStatus();
   int sig = GetSignal();
   if(sig != 0) OpenTrade(sig);
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("EA deinitialized. License state: ", g_LicenseOK ? "OK" : "NOT OK", ", last error: ", g_LastError);
}
//+------------------------------------------------------------------+
