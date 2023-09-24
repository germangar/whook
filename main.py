

import ccxt
from flask import Flask, request, abort
from threading import Timer
import time
import json
import logging
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN


verbose = False
ORDER_TIMEOUT = 40
REFRESH_POSITIONS_FREQUENCY = 5 * 60    # refresh positions every 5 minutes
UPDATE_ORDERS_FREQUENCY = 0.25          # frametime in seconds at which the orders queue is refreshed.
MARGIN_MODE = 'isolated'

def fixVersionFormat( version )->str:
    vl = version.split(".")
    return f'{vl[0]}.{vl[1]}.{vl[2].zfill(3)}'

minCCXTversion = '4.0.69'
CCXTversion = fixVersionFormat(ccxt.__version__)
print( 'CCXT Version:', ccxt.__version__)
if( CCXTversion < fixVersionFormat(minCCXTversion) ):
    print( '\n============== * WARNING * ==============')
    print( 'WHOOK requires CCXT version', minCCXTversion,' or higher.')
    print( 'While it may run with earlier versions wrong behaviors are expected to happen.' )
    print( 'Please update CCXT.' )
    print( '============== * WARNING * ==============\n')
elif( CCXTversion > fixVersionFormat('4.0.88') and CCXTversion < fixVersionFormat('4.0.101') ):
    print( '\n============== * WARNING * ==============')
    print( 'There is a problem with CCXT versions between to 4.0.88 and 4.0.101')
    print( 'when changing marginMode in *Bybit*. Please update CCXT module' )
    print( '============== * WARNING * ==============\n')
    


def dateString():
    return datetime.today().strftime("%Y/%m/%d")

def timeNow():
    return time.strftime("%H:%M:%S")

def floor( number ):
    return number // 1

def ceil( number ):
    return int(-(-number // 1))

def roundUpTick( value: float, tick: str ):
    if type(tick) is not str: tick = str(tick)
    if type(value) is not Decimal: value = Decimal( value )
    return float( value.quantize( Decimal(tick), ROUND_CEILING ) )

def roundDownTick( value: float, tick: str ):
    if type(tick) is not str: tick = str(tick)
    if type(value) is not Decimal: value = Decimal( value )
    return float( value.quantize( Decimal(tick), ROUND_FLOOR ) )

def roundToTick( value: float, tick: float ):
    if type(tick) is not str: tick = str(tick)
    if type(value) is not Decimal: value = Decimal( value )
    return float( value.quantize( Decimal(tick), ROUND_HALF_EVEN ) )

class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)

class position_c:
    def __init__(self, symbol, position, thisMarket = None ) -> None:
        self.symbol = symbol
        self.position = position
        self.thisMarket = thisMarket

    def getKey(cls, key):
        return cls.position.get(key)
    
    def generatePrintString(cls)->str:
        if( cls.thisMarket == None ): 
            return ''
        
        p = 0.0
        unrealizedPnl = 0 if(cls.getKey('unrealizedPnl') == None) else float(cls.getKey('unrealizedPnl'))
        initialMargin = 0 if(cls.getKey('initialMargin') == None) else float(cls.getKey('initialMargin'))
        collateral = 0.0 if(cls.getKey('collateral') == None) else float(cls.getKey('collateral'))
        if( initialMargin != 0 ):
            p = ( unrealizedPnl / initialMargin ) * 100.0
        elif( collateral != 0):
            p = ( unrealizedPnl / (collateral - unrealizedPnl) ) * 100

        positionModeChar = '[H]' if (cls.thisMarket['local']['positionMode'] == 'hedged') else ''
        levStr = "?x" if (cls.thisMarket['local']['leverage'] == 0 ) else str(cls.thisMarket['local']['leverage']) + 'x'

        string = cls.symbol + positionModeChar
        string += ' * ' + cls.thisMarket['local']['marginMode'] + ':' + levStr
        string += ' * ' + cls.getKey('side')
        string += ' * ' + str( cls.getKey('contracts') )
        string += ' * ' + "{:.4f}[$]".format(collateral)
        string += ' * ' + "{:.2f}[$]".format(unrealizedPnl)
        string += ' * ' + "{:.2f}".format(p) + '%'
        return string
            

class order_c:
    def __init__(self, symbol = "", side = "", quantity = 0.0, leverage = 1, delay = 0, reverse = False) -> None:
        self.symbol = symbol
        self.type = 'market'
        self.side = side
        self.quantity = quantity
        self.leverage = leverage
        self.price = None
        self.customID = None
        self.reduced = False
        self.id = ""
        self.delay = delay
        self.reverse = reverse
        self.timestamp = time.monotonic()
    def timedOut(cls):
        return ( cls.timestamp + ORDER_TIMEOUT < time.monotonic() )
    def delayed(cls):
        return (cls.timestamp + cls.delay > time.monotonic() )

class account_c:
    def __init__(self, exchange = None, name = 'default', apiKey = None, secret = None, password = None )->None:
        
        self.accountName = name
        self.canFlipPosition = False
        self.refreshPositionsFailed = 0
        self.positionslist = []
        self.ordersQueue = []
        self.activeOrders = []
        self.SETTLE_COIN = 'USDT'

        if( exchange == None ):
            raise ValueError('Exchange not defined')
        if( name.isnumeric() ):
            print( " * FATAL ERROR: Account 'id' can not be only  numeric" )
            raise ValueError('Invalid Account Name')
        
        if( exchange.lower() == 'kucoinfutures' ):
            self.exchange = ccxt.kucoinfutures( {
                'apiKey': apiKey,
                'secret': secret,
                'password': password,
                #'enableRateLimit': True
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                } )
        elif( exchange.lower() == 'bitget' ):
            self.exchange = ccxt.bitget({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.canFlipPosition = True
        elif( exchange.lower() == 'bingx' ):
            self.exchange = ccxt.bingx({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'coinex' ):
            self.exchange = ccxt.coinex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.canFlipPosition = False
        elif( exchange.lower() == 'phemex' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            ###HACK!! phemex does NOT have setMarginMode when the type is SWAP
            self.exchange.has['setMarginMode'] = False
        elif( exchange.lower() == 'phemexdemo' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
            ###HACK!! phemex does NOT have setMarginMode when the type is SWAP
            self.exchange.has['setMarginMode'] = False
        elif( exchange.lower() == 'bybit' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'bybitdemo' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
        elif( exchange.lower() == 'binance' ):
            self.exchange = ccxt.binance({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'binancedemo' ):
            self.exchange = ccxt.binance({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
        elif( exchange.lower() == 'krakenfutures' ):
            self.exchange = ccxt.krakenfutures({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            # 'options': { 'settlementCurrencies': { 'flex': ['USDT', 'BTC', 'USD', 'GBP', 'EUR', 'USDC'],
        elif( exchange.lower() == 'krakendemo' ):
            self.exchange = ccxt.krakenfutures({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
            self.SETTLE_COIN = 'USD'
            # 'options': { 'settlementCurrencies': { 'flex': ['USDT', 'BTC', 'USD', 'GBP', 'EUR', 'USDC'],
        else:
            raise ValueError('Unsupported exchange')

        if( self.exchange == None ):
            raise ValueError('Exchange creation failed')
        
        # crate a logger for each account
        self.logger = logging.getLogger( self.accountName )
        fh = logging.FileHandler( self.accountName + '.log')
        self.logger.addHandler( fh )
        self.logger.level = logging.INFO

        # Some exchanges don't have all fields properly filled, but we can find out
        # the values in another field. Instead of adding exceptions at each other function
        # let's reconstruct the markets dictionary trying to fix those values
        self.markets = {}
        markets = self.exchange.load_markets()
        marketKeys = markets.keys()
        for key in marketKeys:
            thisMarket = markets[key]
            if( thisMarket.get('settle') != self.SETTLE_COIN ): # double check
                continue

            if( thisMarket.get('contractSize') == None ):
                # in Phemex we can extract the contractSize from the description.
                # it's always going to be 1, but let's handle it in case they change it
                if( self.exchange.id == 'phemex' ):
                    description = thisMarket['info'].get('description')
                    s = description[ description.find('Each contract is worth') + len('Each contract is worth ') : ]
                    list = s.split( ' ', 1 )
                    cs = float( list[0] )
                    if( cs != 1.0 ):
                        print( "* WARNING: phemex", key, "contractSize reported", cs )
                    thisMarket['contractSize'] = cs
                else:
                    print( "WARNING: Market", self.exchange.id, "doesn't have contractSize" )

            # make sure the market has a precision value
            try:
                precision = thisMarket['precision'].get('amount')
            except Exception as e:
                raise ValueError( "Market", self.exchange.id, "doesn't have precision value" )

            # some exchanges don't have a minimum purchase amount defined
            try:
                minAmount = thisMarket['limits']['amount'].get('min')
            except Exception as e:
                minAmount = None
                l = thisMarket.get('limits')
                if( l != None ):
                    a = l.get('amount')
                    if( a != None ):
                        minAmount = a.get('min')

            if( minAmount == None ): # replace minimum amount with precision value
                thisMarket['limits']['amount']['min'] = float(precision)

            # also generate a local list to keep track of marginMode and Leverage status
            thisMarket['local'] = { 'marginMode':'', 'leverage':0, 'positionMode':'' }
            if( self.exchange.has.get('setPositionMode') != True ):
                thisMarket['local']['positionMode'] = 'oneway'
            if( self.exchange.has.get('setMarginMode') != True ):
                thisMarket['local']['marginMode'] = MARGIN_MODE

            # Store the market into the local markets dictionary
            self.markets[key] = thisMarket
            
            
        self.balance = self.fetchBalance()
        self.print( self.balance )
        self.refreshPositions(True)



    ## methods ##

    def print( cls, *args, sep=" ", **kwargs ): # adds account and exchange information to the message
        cls.logger.info( '['+ dateString()+']['+timeNow()+'] ' +sep.join(map(str,args)), **kwargs)
        print( timeNow(), '['+ cls.accountName +'/'+ cls.exchange.id +'] '+sep.join(map(str,args)), **kwargs)


    def verifyLeverageRange( cls, symbol, leverage )->int:

        leverage = max( leverage, 1 )
        maxLeverage = cls.findMaxLeverageForSymbol( symbol )
        
        if( maxLeverage != None and maxLeverage < leverage ):
            cls.print( " * WARNING: Leverage out of bounds. Readjusting to", str(maxLeverage)+"x" )
            leverage = maxLeverage

        # coinex has a list of valid leverage values
        if( cls.exchange.id != 'coinex' ):
            return leverage
        
        thisMarket = cls.markets.get( symbol )
        validLeverages = list(map(int, thisMarket['info']['leverages']))
        safeLeverage = 1
        for value in validLeverages:
            if( value > leverage ):
                break
            safeLeverage = value
        
        return safeLeverage


    def updateSymbolPositionMode( cls, symbol ):
        
        # Make sure the exchange is in oneway mode

        if( cls.exchange.has.get('setPositionMode') != True and cls.markets[ symbol ]['local']['positionMode'] != 'oneway' ):
            print( " * Error: updateSymbolPositionMode: Exchange", cls.exchange.id, "doesn't have setPositionMode nor is set to oneway" )
            return
        
        if( cls.markets[ symbol ]['local']['positionMode'] != 'oneway' and cls.exchange.has.get('setPositionMode') == True ):
            if( cls.getPositionBySymbol(symbol) != None ):
                cls.print( ' * WARNING: Cannot change position mode while a position is open' )
                return
        
            try:
                response = cls.exchange.set_position_mode( False, symbol ) 
            except Exception as e:
                for a in e.args:
                    if( '"retCode":140025' in a or '"code":-4059' in a
                        or 'retCode":110025' in a ):
                        # this is not an error, but just an acknowledge
                        # bybit {"retCode":140025,"retMsg":"position mode not modified","result":{},"retExtInfo":{},"time":1690530385019}
                        # bybit {"retCode":110025,"retMsg":"Position mode is not modified","result":{},"retExtInfo":{},"time":1694988241696}
                        # binance {"code":-4059,"msg":"No need to change position side."}
                        cls.markets[ symbol ]['local']['positionMode'] = 'oneway'
                    else:
                        print( " * Error: updateSymbolLeverage->set_position_mode: Unhandled Exception", a )
            else:
                # was everything correct, tho?
                code = 0
                if( cls.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
                else:
                    code = int(response.get('code'))
                # 'code': '0' <- coinex
                # 'code': '00000' <- bitget
                # 'code': '0' <- phemex
                # 'retCode': '0' <- bybit
                # {'code': '200', 'msg': 'success'} <- binance
                if( cls.exchange.id == 'binance' and code == 200 or code == -4059 ):
                    code = 0

                if( code != 0 ):
                    print( " * Error: updateSymbolLeverage->set_position_mode:", response )
                    return
                
                cls.markets[ symbol ]['local']['positionMode'] = 'oneway'

    
    def updateSymbolLeverage( cls, symbol, leverage ):
        # also sets marginMode to isolated

        if( leverage < 1 ): # leverage 0 indicates we are closing a position
            return
        
        # Notice: Kucoin is never going to make any of these. 
        
        # Coinex doesn't accept any number as leverage. It must be on the list. Also clamp to max allowed
        leverage = cls.verifyLeverageRange( symbol, leverage )
        
        ##########################################
        # Update marginMode if needed
        ##########################################   
        if( cls.markets[ symbol ]['local']['marginMode'] != MARGIN_MODE and cls.exchange.has.get('setMarginMode') == True ):

            params = {}
            # coinex and bybit expect the leverage as part of the marginMode call
            if( cls.exchange.id == 'coinex' or cls.exchange.id == 'bybit' ):
                params['leverage'] = leverage

            try:
                response = cls.exchange.set_margin_mode( MARGIN_MODE, symbol, params )

            except Exception as e:
                for a in e.args:
                    if( '"retCode":140026' in a or "No need to change margin type" in a
                       or '"retCode":110026' in a ):
                        # bybit throws an exception just to inform us the order wasn't neccesary (doh)
                        # bybit {"retCode":140026,"retMsg":"Isolated not modified","result":{},"retExtInfo":{},"time":1690530385642}
                        # bybit setMarginMode() marginMode must be either ISOLATED_MARGIN or REGULAR_MARGIN or PORTFOLIO_MARGIN
                        # bybit {"retCode":110026,"retMsg":"Cross/isolated margin mode is not modified","result":{},"retExtInfo":{},"time":1695526888984}
                        # binance {'code': -4046, 'msg': 'No need to change margin type.'}
                        # updateSymbolLeverage->set_margin_mode: {'code': -4046, 'msg': 'No need to change margin type.'}
                        pass
                    else:
                        print( " * Error: updateSymbolLeverage->set_margin_mode: Unhandled Exception", a )
            else:

                # was everything correct, tho?
                code = 0
                if( cls.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
                else:
                    code = int(response.get('code'))
                # 'code': '0' <- coinex
                # 'code': '00000' <- bitget
                # 'code': '0' <- phemex
                # 'retCode': '0' <- bybit
                # {'code': '200', 'msg': 'success'} <- binance
                if( cls.exchange.id == 'binance' and code == 200 or code == -4046 ):
                    code = 0

                if( code != 0 ):
                    print( " * Error: updateSymbolLeverage->set_margin_mode:", response )
                else:
                    cls.markets[ symbol ]['local']['marginMode'] = MARGIN_MODE

                    # coinex and bybit don't need to continue since they have already updated the leverage
                    if( cls.exchange.id == 'coinex' or cls.exchange.id == 'bybit' ):
                        cls.markets[ symbol ]['local']['leverage'] = leverage
                        return

        ##########################################
        # Finally update leverage
        ##########################################
        if( cls.markets[ symbol ]['local']['leverage'] != leverage and cls.exchange.has.get('setLeverage') == True ):

            # bingx is special
            if( cls.exchange.id == 'bingx' ):
                response = cls.exchange.set_leverage( leverage, symbol, params = {'side':'LONG'} )
                response2 = cls.exchange.set_leverage( leverage, symbol, params = {'side':'SHORT'} )
                if( response.get('code') == '0' and response2.get('code') == '0' ):
                    cls.markets[ symbol ]['local']['leverage'] = leverage
                return

            # from phemex API documentation: The sign of leverageEr indicates margin mode,
            # i.e. leverage <= 0 means cross-margin-mode, leverage > 0 means isolated-margin-mode.
            # we only want isolated so we ignore it

            params = {}
            if( cls.exchange.id == 'coinex' ): # coinex always updates leverage and marginMode at the same time
                params['marginMode'] = cls.markets[ symbol ]['local']['marginMode'] # use current marginMode to avoid triggering an error

            try:
                response = cls.exchange.set_leverage( leverage, symbol, params )
            except Exception as e:
                for a in e.args:
                    if( '"retCode":140043' in a or '"retCode":110043' in a ):
                        # bybit throws an exception just to inform us the order wasn't neccesary (doh)
                        # bybit {"retCode":110043,"retMsg":"Set leverage not modified","result":{},"retExtInfo":{},"time":1694988242174}
                        # bybit {"retCode":140043,"retMsg":"leverage not modified","result":{},"retExtInfo":{},"time":1690530386264}
                        pass
                    elif( 'MAX_LEVERAGE_OUT_OF_BOUNDS' in a ):
                        cls.print( " * Error: Maximum leverage exceeded [", leverage, "]" )
                        return
                        # {"status":"INTERNAL_SERVER_ERROR","result":"error","errors":[{"code":98,"message":"MAX_LEVERAGE_OUT_OF_BOUNDS"}],"serverTime":"2023-09-24T00:57:08.908Z"}
                    else:
                        print( " * Error: updateSymbolLeverage->set_leverage: Unhandled Exception", a )
            else:
                # was everything correct, tho?
                code = 0
                if( cls.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
                elif( cls.exchange.id == 'krakenfutures' ):
                    #{'result': 'success', 'serverTime': '2023-09-22T21:25:47.729Z'}
                    # Error: updateSymbolLeverage->set_leverage: {'result': 'success', 'serverTime': '2023-09-22T21:30:17.767Z'}
                    if( 'success' not in response ):
                        code = -1 if response.get('result') != 'success' else 0
                elif( cls.exchange.id != 'binance' ):
                    code = int(response.get('code'))
                # 'code': '0' <- coinex
                # 'code': '00000' <- bitget
                # 'code': '0' <- phemex
                # 'retCode': '0' <- bybit
                # binance doesn't send any code #{'symbol': 'BTCUSDT', 'leverage': '7', 'maxNotionalValue': '40000000'}
                if( code != 0 ):
                    print( " * Error: updateSymbolLeverage->set_leverage:", response )
                else:
                    cls.markets[ symbol ]['local']['leverage'] = leverage



    def fetchBalance(cls):
        params = { "settle":cls.SETTLE_COIN }
        if( cls.exchange.id == 'krakenfutures' ):
            params['type'] = 'flex'

        response = cls.exchange.fetch_balance( params )

        if( cls.exchange.id == "bitget" ):
            # Bitget response message is all over the place!!
            # so we reconstruct it from the embedded exchange info
            data = response['info'][0]
            balance = {}
            balance['free'] = float( data.get('available') )
            balance['used'] = float( data.get('usdtEquity') ) - float( data.get('available') )
            balance['total'] = float( data.get('usdtEquity') )
            return balance
        if( cls.exchange.id == "coinex" ):
            # Coinex response isn't much better. We also reconstruct it
            data = response['info'].get('data')
            data = data.get(cls.SETTLE_COIN)
            balance = {}
            balance['free'] = float( data.get('available') )
            balance['used'] = float( data.get('margin') )
            balance['total'] = balance['free'] + balance['used'] + float( data.get('profit_unreal') )
            return balance
        if( cls.exchange.id == 'krakenfutures' ):
            data = response['info']['accounts']['flex']
            return { 'free':float(data.get('availableMargin')), 'used':float(data.get('initialMarginWithOrders')), 'total': float(data.get('balanceValue')) }

        return response.get(cls.SETTLE_COIN)
    

    def fetchAvailableBalance(cls)->float:
        return float( cls.fetchBalance().get( 'free' ) )
    

    def fetchBuyPrice(cls, symbol)->float:
        orderbook = cls.exchange.fetch_order_book(symbol)
        ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
        return ask


    def fetchSellPrice(cls, symbol)->float:
        orderbook = cls.exchange.fetch_order_book(symbol)
        bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
        return bid


    def fetchAveragePrice(cls, symbol)->float:
        orderbook = cls.exchange.fetch_order_book(symbol)
        bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
        ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
        return ( bid + ask ) * 0.5


    def getPositionBySymbol(cls, symbol)->position_c:
        for pos in cls.positionslist:
            if( pos.symbol == symbol ):
                return pos
        return None
    

    def findSymbolFromPairName(cls, paircmd):
        # this is only for the pair name we receive in the alert.
        # Once it's converted to ccxt symbol format there is no
        # need to use this method again.

        # first let's check if the pair string contains
        # a backslash. If it does it's probably already a symbol
        if '/' not in paircmd and paircmd.endswith(cls.SETTLE_COIN):
            paircmd = paircmd[:-4]
            paircmd += '/' + cls.SETTLE_COIN + ':' + cls.SETTLE_COIN

        # but it also may not include the ':USDT' ending
        if '/' in paircmd and not paircmd.endswith(':'+ cls.SETTLE_COIN ):
            paircmd += ':' + cls.SETTLE_COIN

        # try the more direct approach
        m = cls.markets.get(paircmd)
        if( m != None ):
            return m.get('symbol')

        # so now let's find it in the list using the id
        for m in cls.markets:
            id = cls.markets[m]['id'] 
            symbol = cls.markets[m]['symbol']
            if( symbol == paircmd or id == paircmd ):
                return symbol
        return None
    

    def findContractSizeForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m == None ):
            cls.print( ' * ERROR: findContractSizeForSymbol called with unknown symbol:', symbol )
            return 1
        return m.get('contractSize')
    

    def findPrecisionForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m == None ):
            cls.print( ' * ERROR: findPrecisionForSymbol called with unknown symbol:', symbol )
            return 1
        return m['precision'].get('amount')
    

    def findMinimumAmountForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m != None ):
            return m['limits']['amount'].get('min')
        return cls.findPrecisionForSymbol( symbol )
    

    def findMaxLeverageForSymbol(cls, symbol)->float:
        #'leverage': {'min': 1.0, 'max': 50.0}}
        m = cls.markets.get(symbol)
        if( m == None ):
            cls.print( ' * ERROR: findMaxLeverageForSymbol called with unknown symbol:', symbol )
            return 0
        maxLeverage = m['limits']['leverage'].get('max')
        if( maxLeverage == None ):
            maxLeverage = 1000
        return maxLeverage


    def contractsFromUSDT(cls, symbol, amount, price, leverage = 1.0 )->float :
        contractSize = cls.findContractSizeForSymbol( symbol )

        coin = Decimal( (amount * leverage) / (contractSize * price) )

        precision = str(cls.findPrecisionForSymbol( symbol ))
        #FIXME! either I have been using precision wrong or binance market description has it wrong.
        if( cls.exchange.id == 'binance' ):
            filters = cls.markets[symbol]['info']['filters']
            for filter in filters:
                if( filter.get('filterType') == 'LOT_SIZE' ):
                    precision = str(filter.get('stepSize'))
                    break

        return roundDownTick( coin, precision ) if ( coin > 0 ) else roundUpTick( coin, precision ) 


    def refreshPositions(cls, v = verbose):
    ### https://docs.ccxt.com/#/?id=position-structure ###
        failed = False
        try:
            positions = cls.exchange.fetch_positions( params = {'settle':cls.SETTLE_COIN} ) # the 'settle' param is only required by phemex

        except Exception as e:
            for a in e.args:
                if a == "OK": # Coinex raises an exception to give an OK message when there are no positions... don't look at me, look at them
                    positions = []
                elif( 'Remote end closed connection' in a
                or '500 Internal Server Error' in a
                or '502 Bad Gateway' in a
                or 'Internal Server Error' in a
                or 'Server busy' in a or 'System busy' in a
                or 'Service is not available' in a
                or '"code":39999' in a
                or '"retCode":10002' in a
                or cls.exchange.id + ' GET' in a ):
                    failed = True
                else:
                    print( timeNow(), cls.exchange.id, '* Refreshpositions:Unknown Exception raised:', a )
                    failed = True

        if( failed ):
            cls.refreshPositionsFailed += 1
            if( cls.refreshPositionsFailed == 10 ):
                print( timeNow(), cls.exchange.id, '* WARNING: Refreshpositions has failed 10 times in a row' )
            return
        
        if (cls.refreshPositionsFailed >= 10 ):
            print( timeNow(), cls.exchange.id, '* Refreshpositions has returned to activity' )

        cls.refreshPositionsFailed = 0
                    
        # Phemex returns positions that were already closed
        # reconstruct the list of positions only with active positions
        cleanPositionsList = []
        for thisPosition in positions:
            if( thisPosition.get('contracts') == 0.0 ):
                continue
            cleanPositionsList.append( thisPosition )
        positions = cleanPositionsList

        numPositions = len(positions)

        if v:
            if( numPositions > 0 ) : print('------------------------------')
            print('Refreshing positions '+cls.accountName+':', numPositions, "positions found" )

        cls.positionslist.clear()
        for thisPosition in positions:

            symbol = thisPosition.get('symbol')

            # HACK!! coinex doesn't have 'contracts'. The value comes in 'contractSize' and in info:{'amount'}
            if( cls.exchange.id == 'coinex' ):
                thisPosition['contracts'] = float( thisPosition['info']['amount'] )

            # HACK!! bybit response doesn't contain a 'hedge' key, but it contains the information in the 'info' block
            if( cls.exchange.id == 'bybit' ):
                thisPosition['hedged'] = True if( thisPosition['info'].get( 'positionIdx' ) != '0' ) else False
            

            # if the position contains positionMode information update our local data
            if( thisPosition.get('hedged') != None ) : # None means the exchange only supports oneWay
                cls.markets[ symbol ]['local'][ 'positionMode' ] = 'hedged' if( thisPosition.get('hedged') == True ) else 'oneway'


            # if the position contains the marginMode information also update the local data

            #some exchanges have the key set to None. Fix it when possible
            if( thisPosition.get('marginMode') == None ) :
                if( cls.exchange.id == 'kucoinfutures' or cls.exchange.id == 'krakenfutures' ):
                    thisPosition['marginMode'] = MARGIN_MODE
                else:
                    print( 'WARNING refreshPositions: Could not get marginMode for', symbol )

            cls.markets[ symbol ]['local'][ 'marginMode' ] = thisPosition.get('marginMode')

            # update the local leverage as well as we can
            leverage = -1
            if( thisPosition.get('leverage') != None ):
                leverage = int(thisPosition.get('leverage'))
                if( leverage != thisPosition.get('leverage') ): # kucoin sends weird fractional leverage. Ignore it
                    leverage = -1

            # still didn't find the leverage, but the exchange has the fetchLeverage method so we can try that.
            if( leverage == -1 and cls.exchange.has.get('fetchLeverage') == True ):
                try:
                    response = cls.exchange.fetch_leverage( symbol )
                except Exception as e:
                    pass
                else:
                    if( cls.exchange.id == 'bitget' ):
                        if( response['data']['marginMode'] == 'crossed' ):
                            leverage = int(response['data'].get('crossMarginLeverage'))
                        else:
                            # they should always be the same
                            longLeverage = int(response['data'].get('fixedLongLeverage'))
                            shortLeverage = int(response['data'].get('fixedShortLeverage'))
                            if( longLeverage == shortLeverage ):
                                leverage = longLeverage

                    elif( cls.exchange.id == 'bingx' ):
                        # they should always be the same
                        longLeverage = response['data'].get('longLeverage')
                        shortLeverage = response['data'].get('shortLeverage')
                        if( longLeverage == shortLeverage ):
                            leverage = longLeverage
            
            if( leverage != -1 ):
                cls.markets[ symbol ]['local'][ 'leverage' ] = leverage
            elif( cls.exchange.id != "kucoinfutures" ): # we know kucoin is helpless
                print( " * WARNING: refreshPositions: Couldn't find leverage for", cls.exchange.id )

            cls.positionslist.append(position_c( symbol, thisPosition, cls.markets[ symbol ] ))

        if v:
            for pos in cls.positionslist:
                print( pos.generatePrintString() )

            print('------------------------------')


    def activeOrderForSymbol(cls, symbol ):
        for o in cls.activeOrders:
            if( o.symbol == symbol ):
                return True
        return False
    

    def fetchClosedOrderById(cls, symbol, id ):
        try:
            response = cls.exchange.fetch_closed_orders( symbol, params = {'settleCoin':cls.SETTLE_COIN} )
        except Exception as e:
            #Exception: ccxt.base.errors.ExchangeError: phemex {"code":39999,"msg":"Please try again.","data":null}
            return None

        for o in response:
            if o.get('id') == id :
                return o
        if verbose : print( "r...", end = '' )
        return None
    

    def fetchOpenOrderById(cls, symbol, id ):
        try:
            response = cls.exchange.fetch_open_orders( symbol, params = {'settleCoin':cls.SETTLE_COIN} )
        except Exception as e:
            #Exception: ccxt.base.errors.ExchangeError: phemex {"code":39999,"msg":"Please try again.","data":null}
            return None

        for o in response:
            if o.get('id') == id :
                return o
        if verbose : print( "r...", end = '' )
        return None
    

    def removeFirstCompletedOrder(cls):
        # go through the queue and remove the first completed order
        for order in cls.activeOrders:
            if( order.timedOut() ):
                cls.print( " * Active Order Timed out", order.symbol, order.side, order.quantity, str(order.leverage)+'x' )
                cls.activeOrders.remove( order )
                continue

            # Phemex doesn't support fetch_order (by id) in swap mode, but it supports fetch_open_orders and fetch_closed_orders
            if( cls.exchange.id == 'phemex' or cls.exchange.id == 'bybit' or cls.exchange.id == 'krakenfutures' ):
                if( order.type == 'limit' ):
                    response = cls.fetchOpenOrderById( order.symbol, order.id )
                else:
                    response = cls.fetchClosedOrderById( order.symbol, order.id )
                if( response == None ):
                    continue
            else:
                try:
                    response = cls.exchange.fetch_order( order.id, order.symbol )
                except Exception as e:
                    if( 'order not exists' in e.args[0] ):
                        continue

                    cls.print( " * removeFirstCompletedOrder: fetch_order unhandled exception raised:", e )
                    continue
                
            
            if( response == None ): # FIXME: Check if this is really happening by printing it.
                print( 'removeFirstCompletedOrder: fetch_order returned None' )
                continue
            if( len(response) == 0 ):
                print( 'removeFirstCompletedOrder: fetch_order returned empty' )
                continue
                        
            status = response.get('status')
            remaining = float( response.get('remaining') )
            price = response.get('price')
            if verbose : print( status, '\nremaining:', remaining, 'price:', price )

            if( order.type == 'limit' ):
                if( cls.exchange.id == 'krakenfutures' ) : response['clientOrderId'] = response['info']['cliOrdId'] #HACK!!
                cls.print( " * Linmit order placed:", order.symbol, order.side, order.quantity, str(order.leverage)+"x", "at price", price, 'id', response.get('clientOrderId') )
                cls.activeOrders.remove( order )
                return True

            if( remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                cls.ordersQueue.append( order_c( order.symbol, order.side, remaining, order.leverage, 0.5 ) )
                cls.activeOrders.remove( order )
                return True
            
            if ( status == 'closed' ):
                cls.print( " * Order succesful:", order.symbol, order.side, order.quantity, str(order.leverage)+"x", "at price", price, 'id', order.id )
                cls.activeOrders.remove( order )
                return True
        return False
    

    def cancelLimitOrder(cls, symbol, customID )->bool:
        if( customID.lower() == 'all' ):
            # def cancel_all_orders(self, symbol: Optional[str] = None, params={}):
            try:
                response = cls.exchange.cancel_all_orders(symbol)
            except Exception as e:
                print( 'Exception:', e )
                # I've tried cancelling when there were no orders but it reported no error. Maybe I missed something.
            else:
                cls.print( 'All', symbol, 'orders have been cancelled' )
                # binance {'code': '200', 'msg': 'The operation of cancel all open order is done.'}
                # phemex {'code': '0', 'msg': '', 'data': '1'}
                # ( a list of orders ) bybit [{'info': {'orderId': '35ef0faf-27e5-44f0-a136-132350da72f0', 'orderLinkId': 'id004'}, 'id': '35ef0faf-27e5-44f0-a136-132350da72f0', 'clientOrderId': 'id004', 'timestamp': None, 'datetime': None, 'lastTradeTimestamp': None, 'lastUpdateTimestamp': None, 'symbol': 'BTC/USDT:USDT', 'type': None, 'timeInForce': None, 'postOnly': None, 'reduceOnly': None, 'side': None, 'price': None, 'stopPrice': None, 'triggerPrice': None, 'takeProfitPrice': None, 'stopLossPrice': None, 'amount': None, 'cost': None, 'average': None, 'filled': None, 'remaining': None, 'status': None, 'fee': None, 'trades': [], 'fees': []}, {'info': {'orderId': 'f1d6a649-0a71-4970-bd78-8eaa2a14f8f5', 'orderLinkId': 'id002'}, 'id': 'f1d6a649-0a71-4970-bd78-8eaa2a14f8f5', 'clientOrderId': 'id002', 'timestamp': None, 'datetime': None, 'lastTradeTimestamp': None, 'lastUpdateTimestamp': None, 'symbol': 'BTC/USDT:USDT', 'type': None, 'timeInForce': None, 'postOnly': None, 'reduceOnly': None, 'side': None, 'price': None, 'stopPrice': None, 'triggerPrice': None, 'takeProfitPrice': None, 'stopLossPrice': None, 'amount': None, 'cost': None, 'average': None, 'filled': None, 'remaining': None, 'status': None, 'fee': None, 'trades': [], 'fees': []}]
            return True
        
        id = customID
        params = {}
        if( cls.exchange.id == 'coinex' ):
            params['order_id'] = customID
        if( cls.exchange.id == 'krakenfutures' ):
            # uuuggggghhhh. why do you do this to me
            try:
                response = cls.exchange.fetch_open_orders( symbol, params = {'settleCoin':cls.SETTLE_COIN} )
            except Exception as e:
                cls.print( 'Unhandlex exception in cancelLimitOrder:', e )
                return
            else:
                for o in response:
                    if( o['info']['cliOrdId'] == customID ):
                        id = o['id']
        elif( cls.exchange.id == 'bybit' ):
            id = None
            params['orderLinkId'] = customID
        else:
            params['clientOrderId'] = customID


        try:
            response = cls.exchange.cancel_order( id, symbol, params )

        except Exception as e:
            for a in e.args:
            # todo: need to check errors in all exchanges
            # phemex {"code":10002,"msg":"OM_ORDER_NOT_FOUND","data":null}
            # bitget {"code":"40020","msg":"Parameter orderId or clientOid error","requestTime":1694984090051,"data":null}
            # coinex: order not exists
            # binance {"code":-2011,"msg":"Unknown order sent."}
                if( 'OM_ORDER_NOT_FOUND' in a or 'order not exists' in a
                   or 'The order cannot be canceled' in a # Kucoin always so helpful
                   or '"code":"40020' in a or '"code":-2011' in a
                   
                   ):
                    cls.print( 'Limit order [', customID, '] not found' )
                else:
                    print( 'cancelLimitOrder: Unhandled exception:', e )

        else:
            cls.print( " * Linmit order [", customID, "] cancelled." )
        return True


    def updateOrdersQueue(cls):

        numOrders = len(cls.ordersQueue) + len(cls.activeOrders)

        # see if any active order was completed and delete it
        while cls.removeFirstCompletedOrder():
            continue

        # if we just cleared the orders queue refresh the positions info
        if( numOrders > 0 and (len(cls.ordersQueue) + len(cls.activeOrders)) == 0 ):
            cls.refreshPositions(True)

        if( len(cls.ordersQueue) == 0 ):
            return
        
        # go through the queue activating every symbol that doesn't have an active order
        for order in cls.ordersQueue:
            if( cls.activeOrderForSymbol(order.symbol) ):
                continue

            if( order.timedOut() ):
                cls.print( timeNow(), " * Order Timed out", order.symbol, order.side, order.quantity, str(order.leverage)+'x' )
                cls.ordersQueue.remove( order )
                continue

            if( order.delayed() ):
                continue

            # disable hedge mode if present
            cls.updateSymbolPositionMode( order.symbol )

            # see if the leverage in the server needs to be changed and set marginMode
            cls.updateSymbolLeverage( order.symbol, order.leverage )

            # set up exchange specific parameters
            params = {}

            if( order.leverage == 0 ): # leverage 0 indicates we are closing a position
                params['reduce'] = True

            if( cls.exchange.id == 'kucoinfutures' ): # Kucoin doesn't use setLeverage nor setMarginMode
                params['leverage'] = max( order.leverage, 1 )
                params['marginMode'] = MARGIN_MODE

            if( cls.exchange.id == 'bitget' ):
                params['side'] = 'buy_single' if( order.side == "buy" ) else 'sell_single'
                if( order.reverse ):
                    params['reverse'] = True

            if( cls.exchange.id == 'bingx' ):
                params['positionSide'] = 'LONG' if order.side == 'buy' else 'SHORT'
            
            if( cls.exchange.id == 'krakenfutures' ):
                params['leverage'] = max( order.leverage, 1 )
                params['marginMode'] = MARGIN_MODE

            if( order.type == 'limit' ):
                if( cls.exchange.id == 'krakenfutures' ):
                    params['cliOrdId'] = order.customID
                else:
                    params['clientOrderId'] = order.customID

            # make sure it's precision adjusted properly
            order.quantity = roundToTick( order.quantity, cls.findPrecisionForSymbol(order.symbol) )

            # send the actual order
            try:
                response = cls.exchange.create_order( order.symbol, order.type, order.side, order.quantity, order.price, params )
                #print( response )
            
            except Exception as e:
                for a in e.args:
                    if 'Too Many Requests' in a or 'too many request' in a or 'service too busy' in a: 
                        #set a bigger delay and try again
                        order.delay += 0.5
                        break
                    #
                    # KUCOIN: kucoinfutures Balance insufficient. The order would cost 304.7268292695.
                    # BITGET: bitget {"code":"40762","msg":"The order size is greater than the max open size","requestTime":1689179675919,"data":null}
                    # BITGET: {"code":"40754","msg":"balance not enough","requestTime":1689363604542,"data":null}
                    # bingx {"code":101204,"msg":"Insufficient margin","data":{}}
                    # phemex {"code":11082,"msg":"TE_CANNOT_COVER_ESTIMATE_ORDER_LOSS","data":null}
                    # phemex {"code":11001,"msg":"TE_NO_ENOUGH_AVAILABLE_BALANCE","data":null}
                    # bybit {"retCode":140007,"retMsg":"remark:order[1643476 23006bb4-630a-4917-af0d-5412aaa1c950] fix price failed for CannotAffordOrderCost.","result":{},"retExtInfo":{},"time":1690540657794}
                    # bybit {"retCode":110007,"retMsg":"Insufficient available balance","result":{},"retExtInfo":{},"
                    # binance "code":-2019,"msg":"Margin is insufficient."
                    # krakenfutures: createOrder failed due to insufficientAvailableFunds
                    elif ( 'Balance insufficient' in a or 'balance not enough' in a 
                            or '"code":"40762"' in a or '"code":"40754" ' in a or '"code":101204' in a
                            or '"code":11082' in a or '"code":11001' in a or '"retCode":110007' in a
                            or '"retCode":140007' in a or 'insufficientAvailableFunds' in a
                            or 'risk limit exceeded.' in a or 'Margin is insufficient' in a ):

                        precision = cls.findPrecisionForSymbol( order.symbol )
                        # try first reducing it to our estimation of current balance
                        if( not order.reduced ):
                            oldQuantity = order.quantity
                            price = cls.fetchSellPrice(order.symbol) if( type == 'sell' ) else cls.fetchBuyPrice(order.symbol)
                            available = cls.fetchAvailableBalance() * 0.985
                            order.quantity = cls.contractsFromUSDT( order.symbol, available, price, order.leverage )
                            order.reduced = True
                            if( order.quantity < cls.findMinimumAmountForSymbol(order.symbol) ):
                                cls.print( ' * Exception raised: Balance insufficient: Minimum contracts required:', cls.findMinimumAmountForSymbol(order.symbol), ' Cancelling')
                                cls.ordersQueue.remove( order )
                            else:
                                cls.print( ' * Exception raised: Balance insufficient: Was', oldQuantity, 'Reducing to', order.quantity, "contracts")
                                
                            break
                        elif( order.quantity > precision ):
                            if( order.quantity < 20 and precision >= 1 ):
                                cls.print( ' * Exception raised: Balance insufficient: Reducing by one contract')
                                order.quantity -= precision
                            else:
                                order.quantity = roundDownTick( order.quantity * 0.95, precision )
                                if( order.quantity < cls.findMinimumAmountForSymbol(order.symbol) ):
                                    cls.print( ' * Exception raised: Balance insufficient: Cancelling' )
                                    cls.ordersQueue.remove( order )
                                else:
                                    cls.print( ' * Exception raised: Balance insufficient: Reducing by 5%')
                            break
                        else: # cancel the order
                            cls.print( ' * Exception raised: Balance insufficient: Cancelling')
                            cls.ordersQueue.remove( order )
                            break

                    elif 'invalidSize' in a:
                        cls.print( ' * Error. Order size invalid:', order.quantity, 'x'+str(order.leverage) )
                        cls.ordersQueue.remove( order )
                        break

                    # bybit {"retCode":20094,"retMsg":"OrderLinkedID is duplicate","result":{},"retExtInfo":{},"time":1694985713343}
                    # binance {"code":-4015,"msg":"Client order id is not valid."}
                    elif '"retCode":20094' in a or '"code":-4015' in a:
                        cls.print( ' * Error Cancelling Linmit order: ID [', order.customID, '] was used before' )
                        cls.ordersQueue.remove( order )
                        break
                        
                    else:
                        # [bitget/bitget] bitget {"code":"45110","msg":"less than the minimum amount 5 USDT","requestTime":1689481837614,"data":null}
                        cls.print( ' * ERROR Cancelling: Unhandled Exception raised:', e )
                        cls.ordersQueue.remove( order )
                        break
                continue # back to the orders loop

            if( response.get('id') == None ):
                cls.print( " * Order denied:", response['info'], "Cancelling" )
                cls.ordersQueue.remove( order )
                continue

            order.id = response.get('id')
            status = response.get('status')
            remaining = response.get('remaining')
            if( remaining != None and remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                cls.ordersQueue.append( order_c( order.symbol, order.side, remaining, order.leverage, 0.5 ) )
                cls.ordersQueue.remove( order )
                continue
            if( (remaining == None or remaining == 0) and response.get('status') == 'closed' ):
                cls.print( " * Order succesful:", order.symbol, order.side, order.quantity, str(order.leverage)+"x", "at price", response.get('price'), 'id', order.id )
                cls.ordersQueue.remove( order )
                cls.refreshPositions(True)
                continue

            if verbose : print( timeNow(), " * Activating Order", order.symbol, order.side, order.quantity, str(order.leverage)+'x', 'id', order.id )
            cls.activeOrders.append( order )
            cls.ordersQueue.remove( order )

accounts = []




def stringToValue( arg )->float:
    try:
        float(arg)
    except ValueError:
        value = None
    else:
        value = float(arg)
    return value

# def is_json( j ):
#     try:
#         json.loads( j )
#     except ValueError as e:
#         return False
#     return True


def updateOrdersQueue():
    for account in accounts:
        account.updateOrdersQueue()


def refreshPositions():
    for account in accounts:
        account.refreshPositions()


def generatePositionsString()->str:
    msg = ''
    for account in accounts:
        account.refreshPositions()
        numPositions = len(account.positionslist)
        msg += '---------------------\n'
        msg += 'Refreshing positions '+account.accountName+': ' + str(numPositions) + ' positions found\n'
        if( numPositions == 0 ):
            continue

        for pos in account.positionslist:
            msg += pos.generatePrintString() + '\n'

    return msg


def parseAlert( data, account: account_c ):

    if( account == None ):
        print( timeNow(), " * ERROR: parseAlert called without an account" )
        return
    
    account.print( ' ' )
    account.print( " ALERT:", data )
    account.print('----------------------------')

    symbol = "Invalid"
    quantity = 0
    leverage = 0
    command = "Invalid"
    isLimit = False
    priceLimit = 0
    isUSDT = False
    isBaseCurrenty = False
    isPercentage = False
    reverse = False


    # Informal plain text syntax
    tokens = data.split()
    for token in tokens:
        if( account.findSymbolFromPairName(token) != None ): # GMXUSDTM, GMX/USDT:USDT and GMX/USDT are all acceptable formats
            symbol = account.findSymbolFromPairName(token) 
        elif ( token == account.accountName ):
            pass
        elif ( token[-1:]  == "$" ): # value in USDT
            isUSDT = True
            arg = token[:-1]
            quantity = stringToValue( arg )
        elif ( token[-1:]  == "@" ): # value in contracts
            arg = token[:-1]
            quantity = stringToValue( arg )
        elif ( token[-1:]  == "%" ): # value in percentage of balance
            arg = token[:-1]
            quantity = stringToValue( arg )
            isPercentage = True
        elif ( token[:1]  == "-" ): # this is a minus symbol! What a bitch (value in base currency)
            isBaseCurrenty = True
            quantity = stringToValue( token )
        elif ( stringToValue( token ) != None ):
            isBaseCurrenty = True
            arg = token
            quantity = stringToValue(arg)
        elif ( token[:1].lower()  == "x" ):
            arg = token[1:]
            leverage = int(stringToValue(arg))
        elif ( token[-1:].lower()  == "x" ):
            arg = token[:-1]
            leverage = int(stringToValue(arg))
        elif token.lower()  == 'long' or token.lower() == "buy":
            command = 'buy'
        elif token.lower()  == 'short' or token.lower() == "sell":
            command = 'sell'
        elif token.lower()  == 'close':
            command = 'close'
        elif token.lower()  == 'position' or token.lower()  == 'pos':
            command = 'position'
        elif ( token[:5].lower()  == "limit" ):
            v = token.split(':')
            if( len(v) != 3 ):
                account.print( " Error: Limit command must be formatted as 'limit:customID:price' ")
                return
            else:
                isLimit = True
                customID = v[1]
                if( len(customID) < 2 or len(customID) > 30 ):
                    account.print( " Error: customID must be longer than 2 characters and shorter than 30' ")
                    return
                priceLimit = stringToValue(v[2])
            if( account.exchange.id == 'coinex' and not customID.isdigit() ):
                account.print( " Error: Coinex only accepts numeric customID' ")
                return

        elif ( token[:6].lower()  == "cancel" ):
            v = token.split(':')
            if( len(v) != 2 ):
                account.print( " Error: Cancel command must be formatted as 'cancel:customID' ")
                return
            command = 'cancel'
            customID = v[1]
            if( len(customID) < 2 or len(customID) > 30 ):
                account.print( " Error: customID must be longer than 2 characters and shorter than 30' ")
                return
            if( account.exchange.id == 'coinex' and not customID.isdigit() ):
                account.print( " Error: Coinex only accepts numeric customID' ")
                return
    

    # validate the commands
    if( symbol == "Invalid"):
        account.print( "ERROR: Couldn't find symbol" )
        return
    if( command == "Invalid" ):
        account.print( "ERROR: Invalid Order: Missing command" )
        return
    if( quantity == None ):
        account.print( "ERROR: Invalid quantity value" )
        return
    if( isLimit and command != 'buy' and command != 'sell' ):
        account.print( "ERROR: Limit orders can only be used with buy/sell commands" )
        return
    if( quantity <= 0 and command == 'buy' ):
        account.print( "ERROR: Invalid Order: Buy must have a positive amount" )
        return
    if( quantity <= 0 and command == 'sell' ):
        if( quantity < 0 ):
            quantity = abs(quantity) #be flexible with sell having a negative amount
        else:
            account.print( "ERROR: Invalid Order: Sell must have an amount" )
            return
    

    #time to put the order on the queue
    
    try:
        available = account.fetchAvailableBalance() * 0.985
    except Exception as e:
        # This is our first communication with the server, and (afaik) it will only fail when the server is not available.
        # I'm still unsure if I should create a queue to retry alerts received while the server was down. By now
        # it will fail to place this order. It's very unlikely to happen, but it has happened.
        # ccxt.base.errors.ExchangeError: Service is not available during funding fee settlement. Please try again later.
        account.print( " ERROR: Order cancelled. Couldn't reach the server:\n", e )
        return
    
    # No point in putting cancel orders in the queue. Just do it and leave.
    if( command == 'cancel' ):
        account.cancelLimitOrder( symbol, customID )
        return
    
    # bybit is too slow at updating positions after an order is made, so make sure they're updated
    if( account.exchange.id == 'bybit' and (command == 'position' or command == 'close') ):
        account.refreshPositions( False )

    minOrder = account.findMinimumAmountForSymbol(symbol)
    leverage = account.verifyLeverageRange( symbol, leverage )

    # quantity is a percentage of the USDT balance
    if( isPercentage ):
        quantity = min( max( quantity, -100.0 ), 100.0 )
        balance = account.fetchBalance()
        if verbose : print( 'PERCENTAGE: ' + str(quantity) + '% =', str( balance['total'] * quantity * 0.01) + '$' )
        quantity = balance['total'] * quantity * 0.01
        isUSDT = True
    
    # convert quantity to concracts if needed
    if( (isUSDT or isBaseCurrenty) and quantity != 0.0 ) :
        # We don't know for sure yet if it's a buy or a sell, so we average
        oldQuantity = quantity
        price = account.fetchAveragePrice(symbol)
        coin_name = account.markets[symbol]['quote']
        if( isBaseCurrenty ) :
            quantity *= price
            coin_name = account.markets[symbol]['base']

        quantity = account.contractsFromUSDT( symbol, quantity, price, leverage )
        if verbose : print( "CONVERTING (x"+str(leverage)+")", oldQuantity, coin_name, '==>', quantity, "contracts" )
        if( abs(quantity) < minOrder ):
            account.print( timeNow(), " * ERROR * Order too small:", quantity, "Minimum required:", minOrder )
            return

    # check for a existing position
    pos = account.getPositionBySymbol( symbol )

    if( command == 'close' or (command == 'position' and quantity == 0) ):
        if pos == None:
            account.print( timeNow(), " * 'Close", symbol, "' No position found" )
            return
        positionContracts = pos.getKey('contracts')
        positionSide = pos.getKey( 'side' )
        if( positionSide == 'long' ):
            account.ordersQueue.append( order_c( symbol, 'sell', positionContracts, 0 ) )
        else: 
            account.ordersQueue.append( order_c( symbol, 'buy', positionContracts, 0 ) )

        return
    
    # position orders are absolute. Convert them to buy/sell order
    if( command == 'position' ):
        if( pos == None ):
            # it's just a straight up buy or sell
            if( quantity < 0 ):
                command = 'sell'
            else:
                command = 'buy'
            quantity = abs(quantity)
        elif( account.markets[symbol]['local']['marginMode'] != MARGIN_MODE ):
            # to change marginMode we need to close the old position first
            if( pos.getKey('side') == 'long' ):
                account.ordersQueue.append( order_c( symbol, 'sell', pos.getKey('contracts'), 0 ) )
            else: 
                account.ordersQueue.append( order_c( symbol, 'buy', pos.getKey('contracts'), 0 ) )
             # Then create the order for the new position
            if( quantity < 0 ):
                command = 'sell'
            else:
                command = 'buy'
            quantity = abs(quantity)
        else:
            # we need to account for the old position
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )
            if( positionSide == 'short' ):
                positionContracts = -positionContracts

            command = 'sell' if positionContracts > quantity else 'buy'
            quantity = abs( quantity - positionContracts )
            if( quantity < minOrder ):
                account.print( " * Order completed: Request matched current position")
                return
        # fall through


    if( command == 'buy' or command == 'sell'):

        # fetch available balance and price
        price = account.fetchSellPrice(symbol) if( command == 'sell' ) else account.fetchBuyPrice(symbol)
        canDoContracts = account.contractsFromUSDT( symbol, available, price, leverage )

        if( pos != None ):
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )
            
            if not isLimit and (( positionSide == 'long' and command == 'sell' ) or ( positionSide == 'short' and command == 'buy' )):
                reverse = True
                # do we need to divide these in 2 orders?
                if( account.exchange.id == 'bitget' and canDoContracts < account.findMinimumAmountForSymbol(symbol) ): #convert it to a reversal
                    print( "Quantity =", quantity, "PositionContracts=", positionContracts )
                    quantity = positionContracts

                if( quantity >= canDoContracts + positionContracts and not account.canFlipPosition ):
                    # we have to make sure each of the orders has the minimum order contracts
                    order1 = canDoContracts + positionContracts
                    order2 = quantity - (canDoContracts + positionContracts)
                    if( order2 < minOrder ):
                        diff = minOrder - order2
                        if( order1 > minOrder + diff ):
                            order1 -= diff

                    # first order is the contracts in the position and the contracs we can afford with the liquidity
                    account.ordersQueue.append( order_c( symbol, command, order1, leverage ) )

                    # second order is whatever we can afford with the former position contracts + the change
                    quantity -= order1
                    if( quantity >= minOrder ): #we are done (should never happen)
                        account.ordersQueue.append( order_c( symbol, command, quantity, leverage, 1.0 ) )

                    return
            # fall through

        if( quantity < minOrder ):
            account.print( timeNow(), " * ERROR * Order too small:", quantity, "Minimum required:", minOrder )
            return

        order = order_c( symbol, command, quantity, leverage, reverse = reverse )
        if( isLimit ):
            order.type = 'limit'
            order.customID = customID
            order.price = priceLimit

        account.ordersQueue.append( order )
        return

    account.print( " * WARNING: Something went wrong. No order was placed")



def Alert( data ):

    account = None

    # first lets find out if there's more than one commands inside the alert message
    lines = data.split("\n")
    for line in lines:
        line = line.rstrip('\n')
        if( len(line) == 0 ):
            continue
        if( line[:2] == '//' ): # if the line begins with // it's a comment and we skip it
            continue
        account = None
        tokens = line.split()
        for token in tokens:
            for a in accounts:
                if( token == a.accountName ):
                    account = a
                    break
        if( account == None ):
            print( timeNow(), ' * ERROR * Account ID not found. ALERT:', line )
            continue

        parseAlert( line.replace('\n', ''), account )




###################
#### Initialize ###
###################

print('----------------------------')

try:
    with open('accounts.json', 'r') as accounts_file:
        accounts_data = json.load(accounts_file)
        accounts_file.close()
except FileNotFoundError:
    with open('accounts.json', 'x') as f:
        f.write( '[\n\t{\n\t\t"EXCHANGE":"kucoinfutures", \n\t\t"ACCOUNT_ID":"your_account_name", \n\t\t"API_KEY":"your_api_key", \n\t\t"SECRET_KEY":"your_secret_key", \n\t\t"PASSWORD":"your_API_password"\n\t}\n]' )
        f.close()
    print( "File 'accounts.json' not found. Template created. Please fill your API Keys into the file and try again")
    print( "Exiting." )
    raise SystemExit()

for ac in accounts_data:

    exchange = ac.get('EXCHANGE')
    if( exchange == None ):
        print( " * ERROR PARSING ACCOUNT INFORMATION: EXCHANGE" )
        continue

    account_id = ac.get('ACCOUNT_ID')
    if( account_id == None ):
        print( " * ERROR PARSING ACCOUNT INFORMATION: ACCOUNT_ID" )
        continue

    api_key = ac.get('API_KEY')
    if( api_key == None ):
        print( " * ERROR PARSING ACCOUNT INFORMATION: API_KEY" )
        continue

    secret_key = ac.get('SECRET_KEY')
    if( secret_key == None ):
        print( " * ERROR PARSING ACCOUNT INFORMATION: SECRET_KEY" )
        continue

    password = ac.get('PASSWORD')
    if( password == None ):
        password = ""
        continue

    print( timeNow(), " * Initializing account: [", account_id, "] in [", exchange , ']')
    try:
        account = account_c( exchange, account_id, api_key, secret_key, password )
    except Exception as e:
        print( 'Account creation failed:', e )
        print('------------------------------')
    else:
        accounts.append( account )

if( len(accounts) == 0 ):
    print( " * FATAL ERROR: No valid accounts found. Please edit 'accounts.json' and introduce your API keys" )
    raise SystemExit()

############################################

# define the webhook server
app = Flask(__name__)
# silencing flask useless spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.disabled = True

@app.route('/whook', methods=['GET','POST'])
def webhook():

    if request.method == 'POST':
        data = request.get_data(as_text=True)
        Alert(data)
        return 'success', 200
    
    if request.method == 'GET':
        # https://b361-139-47-50-177.ngrok-free.app/whook?response=kucoin
        response = request.args.get('response')
        if( response == None ):
            msg = generatePositionsString()
            return app.response_class( msg, mimetype='text/plain; charset=utf-8' )
        
        if response == 'whook':
            return 'WHOOKITYWOOK'

        # Return the requested log file
        try:
            wmsg = open( response+'.log', encoding="utf-8" )
        except FileNotFoundError:
            return 'Not found'
        else:
            text = wmsg.read()
            return app.response_class(text, mimetype='text/plain; charset=utf-8')
        
    else:
        abort(400)

# start the positions fetching loop
timerFetchPositions = RepeatTimer( REFRESH_POSITIONS_FREQUENCY, refreshPositions )
timerFetchPositions.start()

timerOrdersQueue = RepeatTimer( UPDATE_ORDERS_FREQUENCY, updateOrdersQueue )
timerOrdersQueue.start()

# start the webhook server
if __name__ == '__main__':
    print( " * Listening" )
    app.run(host="0.0.0.0", port=80, debug=False)


