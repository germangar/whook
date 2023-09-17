

import ccxt
from flask import Flask, request, abort
from threading import Timer
import time
import json
import logging
from datetime import datetime


verbose = False
ORDER_TIMEOUT = 40
REFRESH_POSITIONS_FREQUENCY = 5 * 60    # refresh positions every 5 minutes
UPDATE_ORDERS_FREQUENCY = 0.25          # frametime in seconds at which the orders queue is refreshed.
MARGIN_MODE = 'isolated'
minCCXTversion = '4.0.69'

if( ccxt.__version__ < minCCXTversion ):
    print( '\n============== * WARNING * ==============')
    print( 'WHOOK requires CCXT version', minCCXTversion,' or higher.')
    print( 'While it may run with earlier versions wrong behaviors are expected to happen.' )
    print( 'Please update CCXT.' )
    print( '============== * WARNING * ==============\n')
else:
    print( 'ccxt version:', ccxt.__version__ )


def dateString():
    return datetime.today().strftime("%Y/%m/%d")

def timeNow():
    return time.strftime("%H:%M:%S")

def floor( number ):
    return number // 1

def ceil( number ):
    return int(-(-number // 1))

def roundUpTick( value, tick )-> float:
    return ceil( value / tick ) * tick

def roundDownTick( value, tick )-> float:
    return floor( value / tick ) * tick

def roundToTick( value, tick )-> float:
    return round( value / tick ) * tick

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
        else:
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
    def __init__(self, symbol = "", type = "", quantity = 0.0, leverage = 1, delay = 0, reverse = False) -> None:
        self.type = type
        self.symbol = symbol
        self.quantity = quantity
        self.leverage = leverage
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
                } )
        elif( exchange.lower() == 'bitget' ):
            self.exchange = ccxt.bitget({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.canFlipPosition = True
        elif( exchange.lower() == 'bingx' ):
            self.exchange = ccxt.bingx({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'coinex' ):
            self.exchange = ccxt.coinex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.canFlipPosition = False
        elif( exchange.lower() == 'mexc' ):
            self.exchange = ccxt.mexc({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'phemex' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
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
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
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
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'bybitdemo' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
        elif( exchange.lower() == 'binance' ):
            self.exchange = ccxt.binance({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'binancedemo' ):
            self.exchange = ccxt.binance({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
        else:
            raise ValueError('Unsupported exchange')

        if( self.exchange == None ):
            raise ValueError('Exchange creation failed')
        
        # crate a logger for each account
        self.logger = logging.getLogger( self.accountName )
        fh = logging.FileHandler( self.accountName + '.log')
        self.logger.addHandler( fh )
        self.logger.level = logging.INFO


        #print( self.exchange.id, 'has setPositionMode:', self.exchange.has.get('setPositionMode') )
        
        # Some exchanges don't have all fields properly filled, but we can find out
        # the values in another field. Instead of adding exceptions at each other function
        # let's reconstruct the markets dictionary trying to fix those values
        self.markets = {}
        markets = self.exchange.load_markets()
        marketKeys = markets.keys()
        for key in marketKeys:
            if( not key.endswith(':USDT') ):  # skip not USDT pairs. All the code is based on USDT
                continue

            thisMarket = markets[key]
            if( thisMarket.get('settle') != 'USDT' ): # double check
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
                    if '"retCode":140025' in a or '"code":-4059' in a:
                        # this is not an error, but just an acknowledge
                        # bybit {"retCode":140025,"retMsg":"position mode not modified","result":{},"retExtInfo":{},"time":1690530385019}
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
                    if( '"retCode":140026' in a or "No need to change margin type" in a ):
                        # bybit throws an exception just to inform us the order wasn't neccesary (doh)
                        # bybit {"retCode":140026,"retMsg":"Isolated not modified","result":{},"retExtInfo":{},"time":1690530385642}
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

            # bingx and mexc are special
            if( cls.exchange.id == 'bingx' ):
                response = cls.exchange.set_leverage( leverage, symbol, params = {'side':'LONG'} )
                response2 = cls.exchange.set_leverage( leverage, symbol, params = {'side':'SHORT'} )
                if( response.get('code') == '0' and response2.get('code') == '0' ):
                    cls.markets[ symbol ]['local']['leverage'] = leverage
                return
            
            if( cls.exchange.id == 'mexc' ):
                cls.exchange.set_leverage( leverage, symbol, params = {'openType': 1, 'positionType': 1} )
                cls.exchange.set_leverage( leverage, symbol, params = {'openType': 1, 'positionType': 2} )
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
                    if( '"retCode":140043' in a ):
                        # bybit throws an exception just to inform us the order wasn't neccesary (doh)
                        # bybit {"retCode":140043,"retMsg":"leverage not modified","result":{},"retExtInfo":{},"time":1690530386264}
                        pass
                    else:
                        print( " * Error: updateSymbolLeverage->set_leverage: Unhandled Exception", a )
            else:
                # was everything correct, tho?
                code = 0
                if( cls.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
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
        params = { "type":"swap" }
        if( cls.exchange.id == "phemex" ):
            params['code'] = 'USDT'
        
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
            data = data.get('USDT')
            balance = {}
            balance['free'] = float( data.get('available') )
            balance['used'] = float( data.get('margin') )
            balance['total'] = balance['free'] + balance['used'] + float( data.get('profit_unreal') )
            return balance
        
        balance = response.get('USDT')
        return balance
    

    def fetchAvailableBalance(cls)->float:
        # Bitget response message is WRONG?
        # if( cls.exchange.id == "bitget" ):
        #     response = cls.fetchBalance()
        #     return response.get( 'free' )
        
        params = { "type":"swap" }
        if( cls.exchange.id == "phemex" ):
            params["code"] = "USDT"

        available = cls.exchange.fetch_free_balance( params )
        return available.get('USDT')
    

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
        if '/' not in paircmd and paircmd.endswith('USDT'):
            paircmd = paircmd[:-4]
            paircmd += '/USDT:USDT'

        # but it also may not include the ':USDT' ending
        if '/' in paircmd and not paircmd.endswith(':USDT'):
            paircmd += ':USDT'

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
        precision = cls.findPrecisionForSymbol( symbol )
        #FIXME! either I have been using precision wrong or binance market description has it wrong.
        if( cls.exchange.id == 'binance' ):
            filters = cls.markets[symbol]['info']['filters']
            for filter in filters:
                if( filter.get('filterType') == 'LOT_SIZE' ):
                    precision = float(filter.get('stepSize'))
                    break
            
        coin = (amount * leverage) / (contractSize * price)
        return roundDownTick( coin, precision ) if ( coin > 0 ) else roundUpTick( coin, precision )
    

    def refreshPositions(cls, v = verbose):
    ### https://docs.ccxt.com/#/?id=position-structure ###
        failed = False
        try:
            positions = cls.exchange.fetch_positions( params = {'settle':'USDT'} ) # the 'settle' param is only required by phemex

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
                if( cls.exchange.id == 'kucoinfutures' ):
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
            response = cls.exchange.fetch_closed_orders( symbol, params = {'settleCoin':'USDT'} )
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
                cls.print( " * Active Order Timed out", order.symbol, order.type, order.quantity, str(order.leverage)+'x' )
                cls.activeOrders.remove( order )
                continue

            # Phemex doesn't support fetch_order (by id) in swap mode, but it supports fetch_open_orders and fetch_closed_orders
            if( cls.exchange.id == 'phemex' or cls.exchange.id == 'bybit' ):
                info = cls.fetchClosedOrderById( order.symbol, order.id )
                if( info == None ):
                    continue
            else:
                try:
                    info = cls.exchange.fetch_order( order.id, order.symbol )
                except Exception as e:
                    if( 'order not exists' in e.args[0] ):
                        continue

                    cls.print( " * removeFirstCompletedOrder: fetch_order unhandled exception raised:", e )
                    continue
                
            
            if( info == None ): # FIXME: Check if this is really happening by printing it.
                print( 'removeFirstCompletedOrder: fetch_order returned None' )
                continue
            if( len(info) == 0 ):
                print( 'removeFirstCompletedOrder: fetch_order returned empty' )
                continue
                        
            status = info.get('status')
            remaining = int( info.get('remaining') )
            price = info.get('price')
            if verbose : print( status, '\nremaining:', remaining, 'price:', price )

            if( remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                cls.ordersQueue.append( order_c( order.symbol, order.type, remaining, order.leverage, 0.5 ) )
                cls.activeOrders.remove( order )
                return True
            
            if ( status == 'closed' ):
                cls.print( " * Order succesful:", order.symbol, order.type, order.quantity, str(order.leverage)+"x", "at price", price, 'id', order.id )
                cls.activeOrders.remove( order )
                return True
        return False


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
                cls.print( timeNow(), " * Order Timed out", order.symbol, order.type, order.quantity, str(order.leverage)+'x' )
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
                params['side'] = 'buy_single' if( order.type == "buy" ) else 'sell_single'
                if( order.reverse ):
                    params['reverse'] = True

            if( cls.exchange.id == 'mexc' ):
                # We could set these up in 'updateSymbolLeverage' but since it can
                # take them it's one less comunication we need to perform
                # openType: 1:isolated, 2:cross - positionMode: 1:hedge, 2:one-way, (no parameter): the user's current config
                # side	int	order direction 1: open long, 2: close short,3: open short 4: close long
                #params['side'] = 1 if( order.type == "buy" ) else 3
                params['openType'] = 1
                params['positionMode'] = 2
                params['marginMode'] = MARGIN_MODE
                params['leverage'] = max( order.leverage, 1 )
                

            # send the actual order
            try:
                response = cls.exchange.create_market_order( order.symbol, order.type, order.quantity, None, params )
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
                    # binance "code":-2019,"msg":"Margin is insufficient."
                    elif ( 'Balance insufficient' in a or 'balance not enough' in a 
                            or '"code":"40762"' in a or '"code":"40754" ' in a or '"code":101204' in a
                            or '"code":11082' in a or '"code":11001' in a
                            or '"retCode":140007' in a 
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
            if verbose : print( timeNow(), " * Activating Order", order.symbol, order.type, order.quantity, str(order.leverage)+'x', 'id', order.id )
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
            
            if ( positionSide == 'long' and command == 'sell' ) or ( positionSide == 'short' and command == 'buy' ):
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

        account.ordersQueue.append( order_c( symbol, command, quantity, leverage, reverse = reverse ) )
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


