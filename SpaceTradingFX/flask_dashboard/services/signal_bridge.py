"""
Space-Trade-Fx Universal Indicator Signal Bridge
Signal Interception & Execution Generator (Memory Buffer & Graphical Object Scanner)

Produces production-grade, ready-to-compile MQL5 Signal Bridge Expert Advisors
capable of intercepting signals from:
1. Memory Buffer Streams (via iCustom and CopyBuffer on buffers 0-15)
2. Chart Graphical Objects (OBJ_ARROW, OBJ_TEXT, OBJ_TREND) for bufferless indicators
3. Dynamic ATR Trailing Stops and CTrade execution
4. Webhook / REST Signal Dispatch to Space-Trade-Fx API
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("space_trading_fx.signal_bridge")


@dataclass
class SignalBridgeConfig:
    """Configuration options for the Space-Trade-Fx Signal Bridge generator."""

    indicator_name: str = "SpaceTradeCustomIndicator"
    bridge_type: str = "buffer"  # "buffer" or "object_scanner"
    magic_number: int = 88300
    lot_size: float = 0.01
    slippage_points: int = 10
    stop_loss_pips: float = 30.0
    take_profit_pips: float = 60.0
    use_atr_trailing_stop: bool = True
    atr_period: int = 14
    atr_multiplier: float = 1.5
    # Buffer Interception options
    buffer_buy_index: int = 0
    buffer_sell_index: int = 1
    buffer_mode: str = "arrow_nonzero"  # "arrow_nonzero", "crossover", "level_threshold"
    threshold_upper: float = 70.0
    threshold_lower: float = 30.0
    indicator_params: list[str] = field(default_factory=list)
    # Object Scanner options
    object_name_prefix: str = "Arrow"
    buy_color_name: str = "clrGreen"
    sell_color_name: str = "clrRed"
    scan_lookback_bars: int = 2
    # Webhook dispatch options
    enable_webhook_dispatch: bool = False
    webhook_url: str = "http://127.0.0.1:5000/api/broker/execute-signal"
    api_token: str = "space-trade-fx-bridge-token"


class SpaceTradeSignalBridge:
    """
    Space-Trade-Fx Universal Indicator Signal Bridge Generator.

    Generates ready-to-compile MQL5 Signal Bridge scripts and Python bridge connectors
    for black-box or compiled indicators.
    """

    def __init__(self, config: SignalBridgeConfig | None = None) -> None:
        self.config = config or SignalBridgeConfig()
        self.logger = logger

    def generate_mql5_code(self, config: SignalBridgeConfig | None = None) -> str:
        """
        Generate complete, robust MQL5 Signal Bridge Expert Advisor code.
        """
        cfg = config or self.config

        if cfg.bridge_type == "object_scanner":
            return self._generate_object_scanner_mql5(cfg)
        else:
            return self._generate_buffer_interceptor_mql5(cfg)

    def _generate_buffer_interceptor_mql5(self, cfg: SignalBridgeConfig) -> str:
        """Generate MQL5 code for buffer interception via iCustom/CopyBuffer."""
        params_str = f', "{cfg.indicator_name}"'
        if cfg.indicator_params:
            params_str += ", " + ", ".join(cfg.indicator_params)

        webhook_code = ""
        webhook_call_buy = 'SendWebhookSignal("BUY", ask);' if cfg.enable_webhook_dispatch else ""
        webhook_call_sell = 'SendWebhookSignal("SELL", bid);' if cfg.enable_webhook_dispatch else ""

        if cfg.enable_webhook_dispatch:
            json_fmt = '{\\"symbol\\":\\"%s\\",\\"action\\":\\"%s\\",\\"price\\":%.5f,\\"magic\\":%I64u}'
            webhook_code = f"""
void SendWebhookSignal(string action, double price)
{{
    char post[];
    char result[];
    string headers = "Content-Type: application/json\\r\\nAuthorization: Bearer {cfg.api_token}\\r\\n";
    string json = StringFormat("{json_fmt}", _Symbol, action, price, InpMagicNumber);
    StringToCharArray(json, post, 0, WHOLE_ARRAY, CP_UTF8);
    string result_headers;
    int res = WebRequest("POST", "{cfg.webhook_url}", headers, 3000, post, result, result_headers);
    if(res == -1)
    {{
        Print("Space-Trade-Fx WebRequest error: ", GetLastError());
    }}
}}
"""

        code = f"""//+------------------------------------------------------------------+
//| Space-Trade-Fx Universal Indicator Signal Bridge                  |
//| Engine: Memory Buffer Interception (iCustom / CopyBuffer)         |
//+------------------------------------------------------------------+
#property copyright   "Space-Trade-Fx"
#property link        "https://space-trade-fx.internal"
#property version     "2.00"
#property description "Space-Trade-Fx Buffer Interception Signal Bridge for {cfg.indicator_name}"
#property strict

#include <Trade\\Trade.mqh>

//--- Inputs
input group "=== Space-Trade-Fx Bridge Settings ==="
input string InpIndicatorName   = "{cfg.indicator_name}"; // Compiled Indicator Name
input int    InpBuyBufferIndex  = {cfg.buffer_buy_index};                   // Buy Signal Buffer Index (0-15)
input int    InpSellBufferIndex = {cfg.buffer_sell_index};                   // Sell Signal Buffer Index (0-15)

input group "=== Risk & Trade Execution ==="
input double InpLotSize         = {cfg.lot_size};                  // Fixed Lot Size
input ulong  InpMagicNumber     = {cfg.magic_number};                 // Magic Number
input ulong  InpSlippage        = {cfg.slippage_points};                    // Slippage Deviation Points
input double InpStopLossPips    = {cfg.stop_loss_pips};                  // Stop Loss in Pips (0 to disable)
input double InpTakeProfitPips  = {cfg.take_profit_pips};                  // Take Profit in Pips (0 to disable)

input group "=== ATR Trailing Stop Engine ==="
input bool   InpUseAtrTrailing  = {"true" if cfg.use_atr_trailing_stop else "false"};                  // Enable Dynamic ATR Trailing Stop
input int    InpAtrPeriod       = {cfg.atr_period};                    // ATR Period
input double InpAtrMultiplier   = {cfg.atr_multiplier};                   // ATR Trailing Multiplier

//--- Global Handles & Objects
CTrade trade;
int    handle_custom_ind = INVALID_HANDLE;
int    handle_atr        = INVALID_HANDLE;
datetime last_bar_time   = 0;

//+------------------------------------------------------------------+
//| Auto-detect broker order filling mode                            |
//+------------------------------------------------------------------+
ENUM_ORDER_FILLING_TYPE GetFillingMode()
{{
    uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
    if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
    if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
    return ORDER_FILLING_RETURN;
}}

//+------------------------------------------------------------------+
//| Detect new bar close                                             |
//+------------------------------------------------------------------+
bool IsNewBar()
{{
    datetime current_bar = iTime(_Symbol, _Period, 0);
    if(current_bar != last_bar_time)
    {{
        last_bar_time = current_bar;
        return true;
    }}
    return false;
}}

//+------------------------------------------------------------------+
//| Apply dynamic ATR trailing stop across open positions            |
//+------------------------------------------------------------------+
void ApplyAtrTrailingStop()
{{
    if(!InpUseAtrTrailing || handle_atr == INVALID_HANDLE) return;

    double atr_buf[];
    ArraySetAsSeries(atr_buf, true);
    if(CopyBuffer(handle_atr, 0, 0, 2, atr_buf) < 2) return;
    double current_atr = atr_buf[0];
    double trail_distance = current_atr * InpAtrMultiplier;

    int total = PositionsTotal();
    for(int i = total - 1; i >= 0; i--)
    {{
        ulong ticket = PositionGetTicket(i);
        if(ticket <= 0) continue;
        if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
        if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

        ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
        double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
        double current_sl = PositionGetDouble(POSITION_SL);
        double current_tp = PositionGetDouble(POSITION_TP);

        if(pos_type == POSITION_TYPE_BUY)
        {{
            double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            double new_sl = NormalizeDouble(bid - trail_distance, _Digits);
            if(bid > open_price && (current_sl == 0.0 || new_sl > current_sl))
            {{
                trade.PositionModify(ticket, new_sl, current_tp);
            }}
        }}
        else if(pos_type == POSITION_TYPE_SELL)
        {{
            double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
            double new_sl = NormalizeDouble(ask + trail_distance, _Digits);
            if(ask < open_price && (current_sl == 0.0 || new_sl < current_sl))
            {{
                trade.PositionModify(ticket, new_sl, current_tp);
            }}
        }}
    }}
}}
{webhook_code}
//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{{
    trade.SetTypeFilling(GetFillingMode());
    trade.SetExpertMagicNumber(InpMagicNumber);
    trade.SetDeviationInPoints(InpSlippage);

    // Initialize custom indicator handle
    handle_custom_ind = iCustom(_Symbol, _Period{params_str});
    if(handle_custom_ind == INVALID_HANDLE)
    {{
        Print("Space-Trade-Fx: Failed to load indicator '", InpIndicatorName, "'. Ensure .ex5 is in MQL5/Indicators/");
        return INIT_FAILED;
    }}

    // Initialize ATR handle for trailing stops
    if(InpUseAtrTrailing)
    {{
        handle_atr = iATR(_Symbol, _Period, InpAtrPeriod);
        if(handle_atr == INVALID_HANDLE)
        {{
            Print("Space-Trade-Fx: Failed to create ATR handle for trailing stop.");
            return INIT_FAILED;
        }}
    }}

    Print("Space-Trade-Fx Universal Buffer Signal Bridge initialized successfully.");
    return(INIT_SUCCEEDED);
}}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{{
    if(handle_custom_ind != INVALID_HANDLE)
        IndicatorRelease(handle_custom_ind);
    if(handle_atr != INVALID_HANDLE)
        IndicatorRelease(handle_atr);
    Print("Space-Trade-Fx Universal Signal Bridge released.");
}}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{{
    // Manage dynamic trailing stop on ticks
    ApplyAtrTrailingStop();

    // Only evaluate new trading signals on bar close
    if(!IsNewBar()) return;

    double buy_buf[];
    double sell_buf[];
    ArraySetAsSeries(buy_buf, true);
    ArraySetAsSeries(sell_buf, true);

    if(CopyBuffer(handle_custom_ind, InpBuyBufferIndex, 1, 2, buy_buf) < 2) return;
    if(CopyBuffer(handle_custom_ind, InpSellBufferIndex, 1, 2, sell_buf) < 2) return;

    double buy_val = buy_buf[0];
    double sell_val = sell_buf[0];

    bool buy_signal = false;
    bool sell_signal = false;

    // Buffer signal rule: Non-empty value (not EMPTY_VALUE, not 0.0, not DBL_MAX)
    if(buy_val != EMPTY_VALUE && buy_val != 0.0 && buy_val != DBL_MAX)
    {{
        buy_signal = true;
    }}
    if(sell_val != EMPTY_VALUE && sell_val != 0.0 && sell_val != DBL_MAX)
    {{
        sell_signal = true;
    }}

    // Check current positions
    int current_positions = 0;
    int total = PositionsTotal();
    for(int i = 0; i < total; i++)
    {{
        if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
            current_positions++;
    }}

    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
    double pip_multiplier = (digits == 3 || digits == 5) ? 10.0 : 1.0;

    if(buy_signal && current_positions == 0)
    {{
        double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
        double sl = (InpStopLossPips > 0) ? NormalizeDouble(ask - InpStopLossPips * pip_multiplier * point, digits) : 0;
        double tp = (InpTakeProfitPips > 0) ? NormalizeDouble(ask + InpTakeProfitPips * pip_multiplier * point, digits) : 0;

        if(trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "SpaceTrade-Buffer-Buy"))
        {{
            Print("Space-Trade-Fx: BUY executed at ", ask);
            {webhook_call_buy}
        }}
    }}
    else if(sell_signal && current_positions == 0)
    {{
        double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
        double sl = (InpStopLossPips > 0) ? NormalizeDouble(bid + InpStopLossPips * pip_multiplier * point, digits) : 0;
        double tp = (InpTakeProfitPips > 0) ? NormalizeDouble(bid - InpTakeProfitPips * pip_multiplier * point, digits) : 0;

        if(trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "SpaceTrade-Buffer-Sell"))
        {{
            Print("Space-Trade-Fx: SELL executed at ", bid);
            {webhook_call_sell}
        }}
    }}
}}
//+------------------------------------------------------------------+
"""
        return code

    def _generate_object_scanner_mql5(self, cfg: SignalBridgeConfig) -> str:
        """
        Generate MQL5 code for DOM / Graphical Object Scanner fallback
        for bufferless visual indicators (OBJ_ARROW, OBJ_TEXT).
        """
        return f"""//+------------------------------------------------------------------+
//| Space-Trade-Fx Universal Indicator Signal Bridge                  |
//| Engine: Chart Graphical Object Scanner (Bufferless Fallback)      |
//+------------------------------------------------------------------+
#property copyright   "Space-Trade-Fx"
#property link        "https://space-trade-fx.internal"
#property version     "2.00"
#property description "Space-Trade-Fx Graphical Object Scanner Bridge"
#property strict

#include <Trade\\Trade.mqh>

//--- Inputs
input group "=== Space-Trade-Fx Object Scanner Settings ==="
input string   InpObjectPrefix    = "{cfg.object_name_prefix}"; // Object Name Prefix Filter
input color    InpBuyColor        = {cfg.buy_color_name};          // Buy Object Color
input color    InpSellColor       = {cfg.sell_color_name};            // Sell Object Color
input int      InpScanLookback    = {cfg.scan_lookback_bars};              // Lookback Bars

input group "=== Risk & Trade Execution ==="
input double   InpLotSize         = {cfg.lot_size};           // Fixed Lot Size
input ulong    InpMagicNumber     = {cfg.magic_number};          // Magic Number
input ulong    InpSlippage        = {cfg.slippage_points};             // Slippage Deviation Points
input double   InpStopLossPips    = {cfg.stop_loss_pips};           // Stop Loss in Pips
input double   InpTakeProfitPips  = {cfg.take_profit_pips};           // Take Profit in Pips

input group "=== ATR Trailing Stop Engine ==="
input bool     InpUseAtrTrailing  = {"true" if cfg.use_atr_trailing_stop else "false"};           // Enable Dynamic ATR Trailing Stop
input int      InpAtrPeriod       = {cfg.atr_period};             // ATR Period
input double   InpAtrMultiplier   = {cfg.atr_multiplier};            // ATR Multiplier

//--- Global State
CTrade trade;
int    handle_atr        = INVALID_HANDLE;
datetime last_processed_signal_time = 0;
string   last_processed_object_name = "";

ENUM_ORDER_FILLING_TYPE GetFillingMode()
{{
    uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
    if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
    if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
    return ORDER_FILLING_RETURN;
}}

void ApplyAtrTrailingStop()
{{
    if(!InpUseAtrTrailing || handle_atr == INVALID_HANDLE) return;

    double atr_buf[];
    ArraySetAsSeries(atr_buf, true);
    if(CopyBuffer(handle_atr, 0, 0, 2, atr_buf) < 2) return;
    double current_atr = atr_buf[0];
    double trail_distance = current_atr * InpAtrMultiplier;

    int total = PositionsTotal();
    for(int i = total - 1; i >= 0; i--)
    {{
        ulong ticket = PositionGetTicket(i);
        if(ticket <= 0) continue;
        if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
        if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

        ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
        double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
        double current_sl = PositionGetDouble(POSITION_SL);
        double current_tp = PositionGetDouble(POSITION_TP);

        if(pos_type == POSITION_TYPE_BUY)
        {{
            double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            double new_sl = NormalizeDouble(bid - trail_distance, _Digits);
            if(bid > open_price && (current_sl == 0.0 || new_sl > current_sl))
                trade.PositionModify(ticket, new_sl, current_tp);
        }}
        else if(pos_type == POSITION_TYPE_SELL)
        {{
            double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
            double new_sl = NormalizeDouble(ask + trail_distance, _Digits);
            if(ask < open_price && (current_sl == 0.0 || new_sl < current_sl))
                trade.PositionModify(ticket, new_sl, current_tp);
        }}
    }}
}}

int OnInit()
{{
    trade.SetTypeFilling(GetFillingMode());
    trade.SetExpertMagicNumber(InpMagicNumber);
    trade.SetDeviationInPoints(InpSlippage);

    if(InpUseAtrTrailing)
    {{
        handle_atr = iATR(_Symbol, _Period, InpAtrPeriod);
        if(handle_atr == INVALID_HANDLE) return INIT_FAILED;
    }}

    Print("Space-Trade-Fx Universal Object Scanner Bridge active.");
    return(INIT_SUCCEEDED);
}}

void OnDeinit(const int reason)
{{
    if(handle_atr != INVALID_HANDLE) IndicatorRelease(handle_atr);
}}

void OnTick()
{{
    ApplyAtrTrailingStop();

    int total_objects = ObjectsTotal(0, 0, -1);
    datetime bar_limit_time = iTime(_Symbol, _Period, InpScanLookback);

    string detected_action = "NONE";
    string target_object = "";

    // Iterate through chart graphical objects
    for(int i = total_objects - 1; i >= 0; i--)
    {{
        string name = ObjectName(0, i, 0, -1);
        if(InpObjectPrefix != "" && StringFind(name, InpObjectPrefix) < 0)
            continue;

        ENUM_OBJECT obj_type = (ENUM_OBJECT)ObjectGetInteger(0, name, OBJPROP_TYPE);
        if(obj_type != OBJ_ARROW && obj_type != OBJ_ARROW_BUY && obj_type != OBJ_ARROW_SELL && obj_type != OBJ_TEXT)
            continue;

        datetime obj_time = (datetime)ObjectGetInteger(0, name, OBJPROP_TIME, 0);
        if(obj_time < bar_limit_time) continue;

        // Debounce: prevent duplicate executions on identical object
        if(name == last_processed_object_name || obj_time <= last_processed_signal_time)
            continue;

        color obj_color = (color)ObjectGetInteger(0, name, OBJPROP_COLOR);
        if(obj_color == InpBuyColor || obj_type == OBJ_ARROW_BUY)
        {{
            detected_action = "BUY";
            target_object = name;
            last_processed_signal_time = obj_time;
            last_processed_object_name = name;
            break;
        }}
        else if(obj_color == InpSellColor || obj_type == OBJ_ARROW_SELL)
        {{
            detected_action = "SELL";
            target_object = name;
            last_processed_signal_time = obj_time;
            last_processed_object_name = name;
            break;
        }}
    }}

    if(detected_action == "NONE") return;

    // Check open positions count
    int open_positions = 0;
    for(int i = 0; i < PositionsTotal(); i++)
    {{
        if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
            open_positions++;
    }}
    if(open_positions > 0) return;

    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
    double pip_multiplier = (digits == 3 || digits == 5) ? 10.0 : 1.0;

    if(detected_action == "BUY")
    {{
        double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
        double sl = (InpStopLossPips > 0) ? NormalizeDouble(ask - InpStopLossPips * pip_multiplier * point, digits) : 0;
        double tp = (InpTakeProfitPips > 0) ? NormalizeDouble(ask + InpTakeProfitPips * pip_multiplier * point, digits) : 0;
        trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "SpaceTrade-Object-Buy");
        Print("Space-Trade-Fx: Object Scanner triggered BUY from object '", target_object, "'");
    }}
    else if(detected_action == "SELL")
    {{
        double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
        double sl = (InpStopLossPips > 0) ? NormalizeDouble(bid + InpStopLossPips * pip_multiplier * point, digits) : 0;
        double tp = (InpTakeProfitPips > 0) ? NormalizeDouble(bid - InpTakeProfitPips * pip_multiplier * point, digits) : 0;
        trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "SpaceTrade-Object-Sell");
        Print("Space-Trade-Fx: Object Scanner triggered SELL from object '", target_object, "'");
    }}
}}
//+------------------------------------------------------------------+
"""

    def generate_python_bridge(self, config: SignalBridgeConfig | None = None) -> str:
        """
        Generate a Space-Trade-Fx Python signal consumer that integrates with
        incoming webhook or polling signals from the MQL5 Signal Bridge.
        """
        cfg = config or self.config
        return f'''"""
Space-Trade-Fx Python Signal Consumer Bridge
Listens for signals dispatched by the Space-Trade-Fx Universal Signal Bridge.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("space_trading_fx.signal_consumer")


class SpaceTradeSignalConsumer:
    """Consumes and routes intercepted signals to connected Space-Trade-Fx broker."""

    def __init__(self, broker_bridge: Any = None) -> None:
        self.broker_bridge = broker_bridge
        self.magic_number = {cfg.magic_number}
        self.default_lot = {cfg.lot_size}

    def process_incoming_signal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        symbol = payload.get("symbol", "EURUSD")
        action = payload.get("action", "HOLD").upper()
        price = float(payload.get("price", 0.0))

        logger.info(f"Space-Trade-Fx Consumer received: {{action}} on {{symbol}} @ {{price}}")

        if action in ("BUY", "SELL") and self.broker_bridge:
            # Route execution to connected broker account
            return self.broker_bridge.execute_signal(
                symbol=symbol,
                action=action,
                lot_size=self.default_lot,
                magic_number=self.magic_number,
            )

        return {{"status": "received", "action": action, "symbol": symbol}}
'''
