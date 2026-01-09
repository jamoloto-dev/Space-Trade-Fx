"""
MetaTrader 5 Connector for SpaceTradingFX
Real MT5 integration for automated trading
"""
import os
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

logger = logging.getLogger(__name__)

# Try to import MetaTrader5 library with proper typing
mt5: Any = None
MT5_AVAILABLE = False
try:
    import MetaTrader5 as mt5_module  # type: ignore
    mt5 = mt5_module
    MT5_AVAILABLE = True
except ImportError:
    logger.warning("MetaTrader5 library not installed. Install with: pip install MetaTrader5")


class MT5Connector:
    """Real MetaTrader 5 connector for trading operations"""
    
    def __init__(self, account: Optional[int] = None, password: Optional[str] = None, 
                 server: Optional[str] = None, path: Optional[str] = None):
        """
        Initialize MT5 connector
        
        Args:
            account: MT5 account number
            password: MT5 account password
            server: MT5 server name (e.g., 'ICMarkets-Demo')
            path: Path to MT5 terminal (optional)
        """
        self.account = account or int(os.environ.get('MT5_ACCOUNT', 0))
        self.password = password or os.environ.get('MT5_PASSWORD', '')
        self.server = server or os.environ.get('MT5_SERVER', '')
        self.path = path or os.environ.get('MT5_PATH', '')
        self.connected = False
        self.last_error = None
    
    def initialize(self) -> bool:
        """Initialize MT5 terminal connection"""
        if not MT5_AVAILABLE or mt5 is None:
            self.last_error = "MetaTrader5 library not installed"
            logger.error(self.last_error)
            return False
        
        try:
            # Initialize MT5
            if self.path:
                init_result = mt5.initialize(path=self.path)
            else:
                init_result = mt5.initialize()
            
            if not init_result:
                self.last_error = f"MT5 initialization failed: {mt5.last_error()}"
                logger.error(self.last_error)
                return False
            
            logger.info("MT5 terminal initialized successfully")
            return True
            
        except Exception as e:
            self.last_error = f"MT5 initialization error: {str(e)}"
            logger.error(self.last_error)
            return False
    
    def login(self) -> bool:
        """Login to MT5 account"""
        if not MT5_AVAILABLE:
            return False
        
        if not self.account or not self.password:
            self.last_error = "Account credentials not provided"
            return False
        
        try:
            authorized = mt5.login(
                login=self.account,
                password=self.password,
                server=self.server
            )
            
            if authorized:
                self.connected = True
                account_info = mt5.account_info()
                logger.info(f"Logged in to MT5 account {self.account} on {self.server}")
                logger.info(f"Balance: {account_info.balance}, Equity: {account_info.equity}")
                return True
            else:
                self.last_error = f"Login failed: {mt5.last_error()}"
                logger.error(self.last_error)
                return False
                
        except Exception as e:
            self.last_error = f"Login error: {str(e)}"
            logger.error(self.last_error)
            return False
    
    def connect(self) -> bool:
        """Initialize and login to MT5"""
        if self.initialize():
            return self.login()
        return False
    
    def disconnect(self):
        """Shutdown MT5 connection"""
        if MT5_AVAILABLE:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 disconnected")
    
    def get_account_info(self) -> Optional[Dict]:
        """Get account information"""
        if not self._check_connection():
            return None
        
        try:
            info = mt5.account_info()
            if info:
                return {
                    'login': info.login,
                    'server': info.server,
                    'balance': info.balance,
                    'equity': info.equity,
                    'margin': info.margin,
                    'free_margin': info.margin_free,
                    'margin_level': info.margin_level,
                    'profit': info.profit,
                    'currency': info.currency,
                    'leverage': info.leverage
                }
            return None
        except Exception as e:
            self.last_error = str(e)
            return None
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get symbol information and current price"""
        if not self._check_connection():
            return None
        
        try:
            # Ensure symbol is selected
            if not mt5.symbol_select(symbol, True):
                self.last_error = f"Symbol {symbol} not found"
                return None
            
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            
            if info and tick:
                return {
                    'symbol': symbol,
                    'bid': tick.bid,
                    'ask': tick.ask,
                    'spread': info.spread,
                    'digits': info.digits,
                    'point': info.point,
                    'volume_min': info.volume_min,
                    'volume_max': info.volume_max,
                    'volume_step': info.volume_step,
                    'trade_mode': info.trade_mode
                }
            return None
        except Exception as e:
            self.last_error = str(e)
            return None
    
    def open_position(self, symbol: str, order_type: str, volume: float,
                      sl: Optional[float] = None, tp: Optional[float] = None, 
                      comment: str = "SpaceTradingFX") -> Optional[Dict]:
        """
        Open a new position
        
        Args:
            symbol: Trading symbol (e.g., 'EURUSD')
            order_type: 'BUY' or 'SELL'
            volume: Lot size
            sl: Stop loss price (optional)
            tp: Take profit price (optional)
            comment: Order comment
            
        Returns:
            Order result dictionary or None on failure
        """
        if not self._check_connection():
            return None
        
        try:
            # Ensure symbol is selected
            if not mt5.symbol_select(symbol, True):
                self.last_error = f"Symbol {symbol} not found"
                return None
            
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                self.last_error = f"Failed to get symbol info for {symbol}"
                return None
            
            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            
            # Determine order type
            if order_type.upper() == 'BUY':
                mt5_order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                mt5_order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            
            # Prepare request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": mt5_order_type,
                "price": price,
                "deviation": 20,
                "magic": 234000,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            if sl:
                request["sl"] = sl
            if tp:
                request["tp"] = tp
            
            # Send order
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.last_error = f"Order failed: {result.comment} (code: {result.retcode})"
                logger.error(self.last_error)
                return None
            
            logger.info(f"Order opened: {order_type} {volume} {symbol} at {price}, ticket: {result.order}")
            
            return {
                'ticket': result.order,
                'symbol': symbol,
                'type': order_type,
                'volume': volume,
                'price': price,
                'sl': sl,
                'tp': tp,
                'comment': comment
            }
            
        except Exception as e:
            self.last_error = f"Order error: {str(e)}"
            logger.error(self.last_error)
            return None
    
    def close_position(self, ticket: int) -> bool:
        """Close a position by ticket"""
        if not self._check_connection():
            return False
        
        try:
            # Get position info
            position = mt5.positions_get(ticket=ticket)
            if not position:
                self.last_error = f"Position {ticket} not found"
                return False
            
            position = position[0]
            symbol = position.symbol
            volume = position.volume
            
            # Determine close type
            if position.type == mt5.POSITION_TYPE_BUY:
                close_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(symbol).bid
            else:
                close_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(symbol).ask
            
            # Close request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": 234000,
                "comment": "Close by SpaceTradingFX",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.last_error = f"Close failed: {result.comment}"
                return False
            
            logger.info(f"Position {ticket} closed at {price}")
            return True
            
        except Exception as e:
            self.last_error = str(e)
            return False
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get open positions"""
        if not self._check_connection():
            return []
        
        try:
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()
            
            if positions is None:
                return []
            
            return [{
                'ticket': p.ticket,
                'symbol': p.symbol,
                'type': 'BUY' if p.type == 0 else 'SELL',
                'volume': p.volume,
                'price_open': p.price_open,
                'price_current': p.price_current,
                'sl': p.sl,
                'tp': p.tp,
                'profit': p.profit,
                'swap': p.swap,
                'time': datetime.fromtimestamp(p.time).isoformat(),
                'comment': p.comment
            } for p in positions]
            
        except Exception as e:
            self.last_error = str(e)
            return []
    
    def get_history(self, days: int = 30) -> List[Dict]:
        """Get trade history"""
        if not self._check_connection():
            return []
        
        try:
            from datetime import timedelta
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)
            
            deals = mt5.history_deals_get(from_date, to_date)
            
            if deals is None:
                return []
            
            return [{
                'ticket': d.ticket,
                'order': d.order,
                'symbol': d.symbol,
                'type': 'BUY' if d.type == 0 else 'SELL',
                'volume': d.volume,
                'price': d.price,
                'profit': d.profit,
                'swap': d.swap,
                'commission': d.commission,
                'time': datetime.fromtimestamp(d.time).isoformat(),
                'comment': d.comment
            } for d in deals if d.symbol]  # Filter out non-trade entries
            
        except Exception as e:
            self.last_error = str(e)
            return []
    
    def modify_position(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
        """Modify position SL/TP"""
        if not self._check_connection():
            return False
        
        try:
            position = mt5.positions_get(ticket=ticket)
            if not position:
                self.last_error = f"Position {ticket} not found"
                return False
            
            position = position[0]
            
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": position.symbol,
                "position": ticket,
                "sl": sl if sl else position.sl,
                "tp": tp if tp else position.tp,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.last_error = f"Modify failed: {result.comment}"
                return False
            
            logger.info(f"Position {ticket} modified: SL={sl}, TP={tp}")
            return True
            
        except Exception as e:
            self.last_error = str(e)
            return False
    
    def _check_connection(self) -> bool:
        """Check if connected to MT5"""
        if not MT5_AVAILABLE or mt5 is None:
            self.last_error = "MetaTrader5 library not available"
            return False
        
        if not self.connected:
            self.last_error = "Not connected to MT5"
            return False
        
        return True
    
    def get_last_error(self) -> str:
        """Get last error message"""
        return self.last_error or "No error"


# Singleton instance for app-wide use
_mt5_connector: Optional[MT5Connector] = None


def get_mt5_connector() -> MT5Connector:
    """Get or create MT5 connector instance"""
    global _mt5_connector
    if _mt5_connector is None:
        _mt5_connector = MT5Connector()
    return _mt5_connector


def is_mt5_available() -> bool:
    """Check if MT5 library is available"""
    return MT5_AVAILABLE
