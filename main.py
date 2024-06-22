

import ccxt
from flask import Flask, request, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from threading import Timer
import time
import json
import copy
import logging
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
from pprint import pprint


def fixVersionFormat( version )->str:
    vl = version.split(".")
    return f'{vl[0]}.{vl[1]}.{vl[2].zfill(3)}'

minCCXTversion = '4.2.82'
CCXTversion = fixVersionFormat(ccxt.__version__)
print( 'CCXT Version:', ccxt.__version__)
if( CCXTversion < fixVersionFormat(minCCXTversion) ):
    print( '\n============== * WARNING * ==============')
    print( 'WHOOK requires CCXT version', minCCXTversion,' or higher.')
    print( 'While it may run with earlier versions wrong behaviors are expected to happen.' )
    print( 'Please update CCXT.' )
    print( '============== * WARNING * ==============\n')
    

###################
##### Globals #####
###################

verbose = False
SHOW_BALANCE = False # print account balance at exchange initialization
SHOW_BREAKEVEN = True # in positions when available
SHOW_ENTRYPRICE = False # in positions
USE_PROXY = False
PORT = 80
PROXY_PORT = 50000
ALERT_TIMEOUT = 60 * 3
ORDER_TIMEOUT = 40
REFRESH_POSITIONS_FREQUENCY = 5 * 60    # refresh positions every 5 minutes
UPDATE_ORDERS_FREQUENCY = 0.25          # frametime in seconds at which the orders queue is refreshed.
TELEGRAM_BOT_TOKEN = ''
TELEGRAM_CHAT_ID = ''
TELEGRAM_WHOOK_URL = ''
TELEGRAM_MODE = 'ADMIN'
MARGIN_MODE_NONE = '------'

#### Open config file #####

def writeConfig():
    with open('config.json', 'w') as f:
        configString = '[\n\t{\n'
        configString += '\t\t"ALERT_TIMEOUT":'+str(ALERT_TIMEOUT)+',\n'
        configString += '\t\t"ORDER_TIMEOUT":'+str(ORDER_TIMEOUT)+',\n'
        configString += '\t\t"REFRESH_POSITIONS_FREQUENCY":'+str(REFRESH_POSITIONS_FREQUENCY)+',\n'
        configString += '\t\t"UPDATE_ORDERS_FREQUENCY":'+str(UPDATE_ORDERS_FREQUENCY)+',\n'
        configString += '\t\t"VERBOSE":'+str(verbose).lower()+',\n'
        configString += '\t\t"SHOW_BALANCE":'+str(SHOW_BALANCE).lower()+',\n'
        configString += '\t\t"SHOW_ENTRYPRICE":'+str(SHOW_ENTRYPRICE).lower()+',\n'
        configString += '\t\t"SHOW_BREAKEVEN":'+str(SHOW_BREAKEVEN).lower()+',\n'
        configString += '\t\t"TELEGRAM_BOT_TOKEN":"'+str(TELEGRAM_BOT_TOKEN)+'",\n'
        configString += '\t\t"TELEGRAM_CHAT_ID":"'+str(TELEGRAM_CHAT_ID)+'",\n'
        configString += '\t\t"TELEGRAM_WHOOK_URL":"'+str(TELEGRAM_WHOOK_URL)+'",\n'
        configString += '\t\t"TELEGRAM_MODE":"'+str(TELEGRAM_MODE).upper()+'",\n'
        configString += '\t\t"USE_PROXY":'+str(USE_PROXY).lower()+',\n'
        configString += '\t\t"PROXY_PORT":'+str(PROXY_PORT)+'\n'
        configString += '\t}\n]'
        
        f.write( configString )
        f.close()

try:
    with open('config.json', 'r') as config_file:
        config = json.load(config_file)
        config = config[0]
        config_file.close()
except FileNotFoundError:
    writeConfig()
    print( "Config file created.\n----------------------------")
else:
    # parse the config file
    if( config.get('ALERT_TIMEOUT') != None ):
        ALERT_TIMEOUT = int(config.get('ALERT_TIMEOUT'))
    if( config.get('ORDER_TIMEOUT') != None ):
        ORDER_TIMEOUT = int(config.get('ORDER_TIMEOUT'))
    if( config.get('REFRESH_POSITIONS_FREQUENCY') != None ):
        REFRESH_POSITIONS_FREQUENCY = int(config.get('REFRESH_POSITIONS_FREQUENCY'))
    if( config.get('UPDATE_ORDERS_FREQUENCY') != None ):
        UPDATE_ORDERS_FREQUENCY = float(config.get('UPDATE_ORDERS_FREQUENCY'))
    if( config.get('SHOW_BALANCE') != None ):
        SHOW_BALANCE = bool(config.get('SHOW_BALANCE'))
    if( config.get('SHOW_ENTRYPRICE') != None ):
        SHOW_BREAKEVEN = bool(config.get('SHOW_ENTRYPRICE'))
    if( config.get('SHOW_BREAKEVEN') != None ):
        SHOW_BREAKEVEN = bool(config.get('SHOW_BREAKEVEN'))
    if( config.get('VERBOSE') != None ):
        verbose = bool(config.get('VERBOSE'))
    if( config.get('TELEGRAM_BOT_TOKEN') != None ):
        TELEGRAM_BOT_TOKEN = str(config.get('TELEGRAM_BOT_TOKEN'))
    if( config.get('TELEGRAM_CHAT_ID') != None ):
        TELEGRAM_CHAT_ID = str(config.get('TELEGRAM_CHAT_ID'))
    if( config.get('TELEGRAM_WHOOK_URL') != None ):
        TELEGRAM_WHOOK_URL = str(config.get('TELEGRAM_WHOOK_URL'))
    if( config.get('TELEGRAM_MODE') != None ):
        TELEGRAM_MODE = str(config.get('TELEGRAM_MODE')).upper()
        if( TELEGRAM_MODE != 'ADMIN' and TELEGRAM_MODE != 'PUCLIC' ):
            print( "Telegram mode must be either 'admin' or 'public. Resetting to 'admin'" )
            TELEGRAM_MODE = 'ADMIN'
    if( config.get('USE_PROXY') != None ):
        USE_PROXY = bool(config.get('USE_PROXY'))
    if( config.get('PROXY_PORT') != None ):
        PROXY_PORT = int(config.get('PROXY_PORT'))
    #rewrite the config file
    writeConfig()

##### Initialize telegram bot ######

if TELEGRAM_BOT_TOKEN != '':
    try:
        import telegram
        from telegram import Bot as telegram_bot, Update as telegram_update
    except ImportError:
        print( "Telegram module not present")
        print( "If you intend to use the telegram alerts use: 'pip install python-telegram-bot==13.7' to obtain the module")
    else:
        if( telegram.__version__ != '13.7' ):
            print( 'Telegram module: python-telegram-bot version is not 13.7' )
            print( "Please make sure to install the correct version with: 'pip install python-telegram-bot==13.7'" )
            TELEGRAM_BOT_TOKEN = ''

# load the bot
telegramBot = None
try:
    if( TELEGRAM_BOT_TOKEN != '' ):
        telegramBot = telegram_bot(token=TELEGRAM_BOT_TOKEN)
except Exception as e:
    telegramBot = None
    print( "Couldn't initializate telegram bot:", e )
else:
    if( telegramBot != None ):
        print( "Telegram bot connected" )
        telegramBot.set_webhook(url=TELEGRAM_WHOOK_URL)

def telegramAdminMsg( *args, sep=" ", **kwargs ):
    if telegramBot != None and TELEGRAM_BOT_TOKEN != '' and TELEGRAM_MODE == 'ADMIN':
        telegramBot.send_message(chat_id=TELEGRAM_CHAT_ID, text = sep.join(map(str, args)) )

##### Utils #####

def dateString():
    return datetime.today().strftime("%Y/%m/%d")

def timeNow():
    return time.strftime("%H:%M:%S")

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

    def getKey(self, key):
        return self.position.get(key)
    
    def generatePrintString(self)->str:
        if( self.thisMarket == None ): 
            return ''
        
        p = 0.0
        unrealizedPnl = 0 if(self.getKey('unrealizedPnl') == None) else float(self.getKey('unrealizedPnl'))
        initialMargin = 0 if(self.getKey('initialMargin') == None) else float(self.getKey('initialMargin'))
        collateral = 0.0 if(self.getKey('collateral') == None) else float(self.getKey('collateral'))
        if( initialMargin != 0 ):
            p = ( unrealizedPnl / initialMargin ) * 100.0
        elif( collateral != 0):
            p = ( unrealizedPnl / (collateral - unrealizedPnl) ) * 100

        positionModeChar = '[H]' if (self.thisMarket['local']['positionMode'] == 'hedged') else ''
        levStr = "?x" if (self.thisMarket['local']['leverage'] == 0 ) else str(self.thisMarket['local']['leverage']) + 'x'

        string = self.symbol + positionModeChar
        string += ' * ' + self.thisMarket['local']['marginMode'] + ':' + levStr
        string += ' * ' + self.getKey('side')
        string += ' * ' + str( self.getKey('contracts') )
        if( initialMargin != 0 ) : string += ' * ' + "{:.4f}[$]".format(initialMargin)
        elif( collateral != 0) : string += ' * ' + "{:.4f}[$]".format(collateral)
        string += ' * ' + "{:.2f}[$]".format(unrealizedPnl)
        string += ' * ' + "{:.2f}".format(p) + '%'

        if( self.getKey('entryPrice') != None ):
            string += ' * ' + "[ep]{:.3f}".format(float(self.getKey('entryPrice')))

        # OKX and Bitget provide the position breakeven price info:bePx. Let's print that too
        if( self.getKey('info') != None ):
            be = self.getKey('info').get('bePx')
            if( be == None ):
                be = self.getKey('info').get('breakEvenPrice')

            if( be != None and SHOW_BREAKEVEN ):
                string += ' * ' + "[be]{:.4f}".format(float(be))

        return string
            

class order_c:
    def __init__(self, symbol = "", side = "", quantity = 0.0, leverage = 1, delay = 0, reduceOnly = False) -> None:
        self.symbol = symbol
        self.type = 'market'
        self.side = side
        self.quantity = quantity
        self.leverage = leverage
        self.price = None
        self.customID = None
        self.reduced = False
        self.reduceOnly = True if leverage == 0 else reduceOnly
        self.id = ""
        self.delay = delay
        self.timestamp = time.monotonic()
    def timedOut(self):
        return ( self.timestamp + ORDER_TIMEOUT < time.monotonic() )
    def delayed(self):
        return (self.timestamp + self.delay > time.monotonic() )

class account_c:
    def __init__(self, exchange = None, name = 'default', apiKey = None, secret = None, password = None, marginMode = None, settleCoin = None )->None:
        
        self.accountName = name
        self.refreshPositionsFailed = 0
        self.positionslist = []
        self.ordersQueue = []
        self.activeOrders = []
        self.latchedAlerts = []
        self.MARGIN_MODE = 'cross' if ( marginMode != None and marginMode.lower() == 'cross') else 'isolated'
        self.SETTLE_COIN = 'USDT' if( settleCoin == None ) else settleCoin

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
                'enableRateLimit': False,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                } )
        elif( exchange.lower() == 'bitget' ):
            self.exchange = ccxt.bitget({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": False
                })
        elif( exchange.lower() == 'bingx' ):
            self.exchange = ccxt.bingx({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": False
                })
        elif( exchange.lower() == 'coinex' ):
            self.exchange = ccxt.coinex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": False
                })
        elif( exchange.lower() == 'phemex' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": False
                })
            ###HACK!! phemex does NOT have setMarginMode when the type is SWAP
            self.exchange.has['setMarginMode'] = False
        elif( exchange.lower() == 'phemexdemo' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": False
                })
            self.exchange.set_sandbox_mode( True )
            ###HACK!! phemex does NOT have setMarginMode when the type is SWAP
            self.exchange.has['setMarginMode'] = False
        elif( exchange.lower() == 'bybit' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'bybitdemo' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
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
                "enableRateLimit": False
                })
        elif( exchange.lower() == 'binancedemo' ):
            self.exchange = ccxt.binance({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": False
                })
            self.exchange.set_sandbox_mode( True )
        elif( exchange.lower() == 'krakenfutures' ):
            self.exchange = ccxt.krakenfutures({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.SETTLE_COIN = 'USD'
            if( settleCoin != None ) : self.SETTLE_COIN = settleCoin
            # 'options': { 'settlementCurrencies': { 'flex': ['USDT', 'BTC', 'USD', 'GBP', 'EUR', 'USDC'],
        elif( exchange.lower() == 'krakendemo' ):
            self.exchange = ccxt.krakenfutures({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'defaultMarginMode':self.MARGIN_MODE, 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
            self.SETTLE_COIN = 'USD'
            if( settleCoin != None ) : self.SETTLE_COIN = settleCoin
            # 'options': { 'settlementCurrencies': { 'flex': ['USDT', 'BTC', 'USD', 'GBP', 'EUR', 'USDC'],
        elif( exchange.lower() == 'okx' ):
            self.exchange = ccxt.okx ({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'okxdemo' ):
            self.exchange = ccxt.okx ({
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


            # HACK: Bingx has wrong leverage limits defined
            if( self.exchange.id == 'bingx' ):
                thisMarket['limits']['leverage']['max'] = None if self.exchange.has['fetchLeverage'] else max( 100, thisMarket['limits']['leverage']['max'] )

            # also generate a local list to keep track of marginMode and Leverage status
            thisMarket['local'] = { 'marginMode':MARGIN_MODE_NONE, 'leverage':0, 'positionMode':'' }
            if( self.exchange.has.get('setPositionMode') != True ):
                thisMarket['local']['positionMode'] = 'oneway'

            # Store the market into the local markets dictionary
            self.markets[key] = thisMarket

        if( verbose ):
            pprint( self.markets['BTC/' + self.SETTLE_COIN + ':' + self.SETTLE_COIN] )
            
        self.refreshPositions(True)



    ## methods ##

    def print( self, *args, sep=" ", **kwargs ): # adds account and exchange information to the message
        self.logger.info( '['+ dateString()+']['+timeNow()+'] ' +sep.join(map(str,args)), **kwargs)
        print( timeNow(), '['+ self.accountName +'/'+ self.exchange.id +'] '+ sep.join(map(str,args)), **kwargs )
        if( args[0].startswith(' * E:') ):
            telegramAdminMsg( '['+ self.accountName +'/'+ self.exchange.id +']\n'+ sep.join(map(str,args)), **kwargs )

    def verifyLeverageRange( self, symbol, leverage )->int:

        leverage = max( leverage, 1 )
        maxLeverage = self.findMaxLeverageForSymbol( symbol )
        
        if( maxLeverage != None and maxLeverage < leverage ):
            self.print( " * WARNING: Leverage out of bounds. Readjusting to", str(maxLeverage)+"x" )
            leverage = maxLeverage

        # coinex has a list of valid leverage values
        if( self.exchange.id != 'coinex' ):
            return leverage
        
        thisMarket = self.markets.get( symbol )
        leverages = thisMarket['info'].get('leverage')
        if( leverages == None ):
            leverages = thisMarket['info'].get('leverages')
        validLeverages = list(map(int, leverages))
        safeLeverage = 1
        for value in validLeverages:
            if( value > leverage ):
                break
            safeLeverage = value
        
        return safeLeverage


    def updateSymbolPositionMode( self, symbol ):
        
        # Make sure the exchange is in oneway mode

        if( self.exchange.has.get('setPositionMode') != True and self.markets[ symbol ]['local']['positionMode'] != 'oneway' ):
            print( " * E: updateSymbolPositionMode: Exchange", self.exchange.id, "doesn't have setPositionMode nor is set to oneway" )
            return
        
        if( self.markets[ symbol ]['local']['positionMode'] != 'oneway' and self.exchange.has.get('setPositionMode') == True ):
            if( self.getPositionBySymbol(symbol) != None ):
                self.print( ' * W: Cannot change position mode while a position is open' )
                return
        
            try:
                response = self.exchange.set_position_mode( False, symbol )
            except ccxt.NoChange as e:
                self.markets[ symbol ]['local']['positionMode'] = 'oneway'
            except Exception as e:
                for a in e.args:
                    if( '"retCode":140025' in a or '"code":-4059' in a
                        or 'retCode":110025' in a or '"code":"59000"' in a ):
                        # this is not an error, but just an acknowledge
                        # bybit {"retCode":140025,"retMsg":"position mode not modified","result":{},"retExtInfo":{},"time":1690530385019}
                        # bybit {"retCode":110025,"retMsg":"Position mode is not modified","result":{},"retExtInfo":{},"time":1694988241696}
                        # binance {"code":-4059,"msg":"No need to change position side."}
                        # okx {"code":"59000","data":[],"msg":"Setting failed. Cancel any open orders, close positions, and stop trading bots first."}
                        self.markets[ symbol ]['local']['positionMode'] = 'oneway'
                    else:
                        print( " * E: updateSymbolLeverage->set_position_mode:", a, type(e) )
            else:
                # was everything correct, tho?
                code = 0
                if( self.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
                else:
                    code = int(response.get('code'))
                # 'code': '0' <- coinex
                # 'code': '00000' <- bitget
                # 'code': '0' <- phemex
                # 'retCode': '0' <- bybit
                # {'code': '200', 'msg': 'success'} <- binance
                if( self.exchange.id == 'binance' and code == 200 or code == -4059 ):
                    code = 0

                if( code != 0 ):
                    print( " * E: updateSymbolLeverage->set_position_mode:", response )
                    return
                
                self.markets[ symbol ]['local']['positionMode'] = 'oneway'

    
    def updateSymbolLeverage( self, symbol, leverage ):
        # also sets marginMode

        if( leverage < 1 ): # leverage 0 indicates we are closing a position
            return
        
        # Notice: Kucoin is never going to make any of these. 
        
        # Coinex doesn't accept any number as leverage. It must be on the list. Also clamp to max allowed
        leverage = self.verifyLeverageRange( symbol, leverage )
        
        ##########################################
        # Update marginMode if needed
        ##########################################   
        if( self.markets[ symbol ]['local']['marginMode'] != self.MARGIN_MODE and self.exchange.has.get('setMarginMode') == True ):

            params = {}
            # coinex and bybit expect the leverage as part of the marginMode call
            if( self.exchange.id == 'coinex' or self.exchange.id == 'bybit' ):
                params['leverage'] = leverage
            elif( self.exchange.id == 'okx' ):
                params['lever'] = leverage

            try:
                response = self.exchange.set_margin_mode( self.MARGIN_MODE, symbol, params )

            except ccxt.NoChange as e:
                self.markets[ symbol ]['local']['marginMode'] = self.MARGIN_MODE
            except ccxt.MarginModeAlreadySet as e:
                self.markets[ symbol ]['local']['marginMode'] = self.MARGIN_MODE
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
                        self.markets[ symbol ]['local']['marginMode'] = self.MARGIN_MODE
                    else:
                        print( " * E: updateSymbolLeverage->set_margin_mode:", a, type(e) )
            else:

                # was everything correct, tho?
                code = 0
                if( self.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
                else:
                    code = int(response.get('code'))
                # 'code': '0' <- coinex
                # 'code': '00000' <- bitget
                # 'code': '0' <- phemex
                # 'retCode': '0' <- bybit
                # {'code': '200', 'msg': 'success'} <- binance
                if( self.exchange.id == 'binance' and code == 200 or code == -4046 ):
                    code = 0

                if( code != 0 ):
                    print( " * E: updateSymbolLeverage->set_margin_mode:", response )
                else:
                    self.markets[ symbol ]['local']['marginMode'] = self.MARGIN_MODE

                    # coinex and bybit don't need to continue since they have already updated the leverage
                    if( self.exchange.id == 'coinex' or self.exchange.id == 'bybit' ):
                        self.markets[ symbol ]['local']['leverage'] = leverage
                        return

        ##########################################
        # Finally update leverage
        ##########################################
        if( self.markets[ symbol ]['local']['leverage'] != leverage and self.exchange.has.get('setLeverage') == True ):

            # from phemex API documentation: The sign of leverageEr indicates margin mode,
            # i.e. leverage <= 0 means cross-margin-mode, leverage > 0 means isolated-margin-mode.

            params = {}
            if( self.exchange.id == 'coinex' ): # coinex always updates leverage and marginMode at the same time
                params['marginMode'] = self.markets[ symbol ]['local']['marginMode'] # use current marginMode to avoid triggering an error
            elif( self.exchange.id == 'okx' ):
                params['marginMode'] = self.markets[ symbol ]['local']['marginMode']
                params['posSide'] = 'net'
            elif( self.exchange.id == 'bingx' ):
                if( self.markets[ symbol ]['local']['positionMode'] != 'oneway' ):
                    response = self.exchange.set_leverage( leverage, symbol, params = {'side':'LONG'} )
                    response2 = self.exchange.set_leverage( leverage, symbol, params = {'side':'SHORT'} )
                    if( response.get('code') == '0' and response2.get('code') == '0' ):
                        self.markets[ symbol ]['local']['leverage'] = leverage
                    return
                else:
                    params['side'] = 'BOTH'

            try:
                response = self.exchange.set_leverage( leverage, symbol, params )
            except ccxt.NoChange as e:
                self.markets[ symbol ]['local']['leverage'] = leverage
            except Exception as e:
                for a in e.args:
                    if( '"retCode":140043' in a or '"retCode":110043' in a ):
                        # bybit throws an exception just to inform us the order wasn't neccesary (doh)
                        # bybit {"retCode":110043,"retMsg":"Set leverage not modified","result":{},"retExtInfo":{},"time":1694988242174}
                        # bybit {"retCode":140043,"retMsg":"leverage not modified","result":{},"retExtInfo":{},"time":1690530386264}
                        pass
                    elif( 'MAX_LEVERAGE_OUT_OF_BOUNDS' in a ):
                        self.print( " * E: Maximum leverage exceeded [", leverage, "]" )
                        return
                        # {"status":"INTERNAL_SERVER_ERROR","result":"error","errors":[{"code":98,"message":"MAX_LEVERAGE_OUT_OF_BOUNDS"}],"serverTime":"2023-09-24T00:57:08.908Z"}
                    else:
                        print( " * E: updateSymbolLeverage->set_leverage:", a, type(e) )
            else:
                # was everything correct, tho?
                code = 0
                if( self.exchange.id == 'bybit' ): # they didn't receive enough love as children
                    code = int(response.get('retCode'))
                elif( self.exchange.id == 'krakenfutures' ):
                    #{'result': 'success', 'serverTime': '2023-09-22T21:25:47.729Z'}
                    # Error: updateSymbolLeverage->set_leverage: {'result': 'success', 'serverTime': '2023-09-22T21:30:17.767Z'}
                    if( 'success' not in response ):
                        code = -1 if response.get('result') != 'success' else 0
                elif( self.exchange.id != 'binance' ):
                    code = int(response.get('code'))
                # 'code': '0' <- coinex
                # 'code': '00000' <- bitget
                # 'code': '0' <- phemex
                # 'retCode': '0' <- bybit
                # binance doesn't send any code #{'symbol': 'BTCUSDT', 'leverage': '7', 'maxNotionalValue': '40000000'}
                if( code != 0 ):
                    print( " * E: updateSymbolLeverage->set_leverage:", response )
                else:
                    self.markets[ symbol ]['local']['leverage'] = leverage



    def fetchBalance(self):
        params = { "settle":self.SETTLE_COIN }
        if( self.exchange.id == 'krakenfutures' ):
            params['type'] = 'flex'

        response = self.exchange.fetch_balance( params )

        if( self.exchange.id == 'krakenfutures' ):
            data = response['info']['accounts']['flex']
            return { 'free':float(data.get('availableMargin')), 'used':float(data.get('initialMarginWithOrders')), 'total': float(data.get('balanceValue')) }

        if( response.get(self.SETTLE_COIN) == None ):
            balance = { 'free':0.0, 'used':0.0, 'total':0.0 }
            return balance
        
        return response.get(self.SETTLE_COIN)
    

    def fetchAvailableBalance(self)->float:
        return float( self.fetchBalance().get( 'free' ) )
    

    def fetchBuyPrice(self, symbol)->float:
        orderbook = self.exchange.fetch_order_book(symbol)
        ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
        if( ask == None ):
            raise ValueError( "Couldn't fetch ask price" )
        return ask


    def fetchSellPrice(self, symbol)->float:
        orderbook = self.exchange.fetch_order_book(symbol)
        bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
        if( bid == None ):
            raise ValueError( "Couldn't fetch bid price" )
        return bid


    def fetchAveragePrice(self, symbol)->float:
        orderbook = self.exchange.fetch_order_book(symbol)
        bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
        ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
        if( bid == None and ask == None ):
            raise ValueError( "Couldn't fetch orderbook" )
        if( bid == None ): bid = ask
        if( ask == None ): ask = bid
        return ( bid + ask ) * 0.5


    def getPositionBySymbol(self, symbol)->position_c:
        for pos in self.positionslist:
            if( pos.symbol == symbol ):
                return pos
        return None
    

    def findSymbolFromPairName(self, pairString):
        # this is only for the pair name we receive in the alert.
        # Once it's converted to ccxt symbol format there is no
        # need to use this method again.

        paircmd = pairString.upper()

        if( paircmd.endswith('.P' ) ):
            paircmd = paircmd[:-2]

        # first let's check if the pair string contains
        # a backslash. If it does it's probably already a symbol
        if '/' not in paircmd and paircmd.endswith(self.SETTLE_COIN):
            paircmd = paircmd[:-len(self.SETTLE_COIN)]
            paircmd += '/' + self.SETTLE_COIN + ':' + self.SETTLE_COIN

        # but it also may not include the ':USDT' ending
        if '/' in paircmd and not paircmd.endswith(':'+ self.SETTLE_COIN ):
            paircmd += ':' + self.SETTLE_COIN

        # try the more direct approach
        m = self.markets.get(paircmd)
        if( m != None ):
            return m.get('symbol')

        # so now let's find it in the list using the id
        for m in self.markets:
            id = self.markets[m]['id'] 
            symbol = self.markets[m]['symbol']
            if( symbol == paircmd or id == paircmd ):
                return symbol
        return None
    

    def findContractSizeForSymbol(self, symbol)->float:
        return self.markets[symbol].get('contractSize')
    

    def findPrecisionForSymbol(self, symbol)->float:
        if( self.exchange.id == 'binance' or self.exchange.id == 'bingx' ):
            precision = 1.0 / (10.0 ** self.markets[symbol]['precision'].get('amount'))
        else :
            precision = self.markets[symbol]['precision'].get('amount')
        return precision
    

    def findMinimumAmountForSymbol(self, symbol)->float:
        return self.markets[symbol]['limits']['amount'].get('min')
    

    def findMaxLeverageForSymbol(self, symbol)->float:
        maxLeverage = self.markets[symbol]['limits']['leverage'].get('max')
        if( maxLeverage == None ):
            maxLeverage = 100
            if( self.exchange.has['fetchLeverage'] ):
                info = self.exchange.fetch_leverage( symbol ).get('info')

                if( info != None and info.get('maxLongLeverage') != None and info.get('maxShortLeverage') != None ):
                    maxLeverage = min(int(info['maxLongLeverage']), int(info['maxShortLeverage']))

            self.markets[symbol]['limits']['leverage']['max'] = maxLeverage

        return maxLeverage


    def contractsFromUSDT(self, symbol, amount, price, leverage = 1.0 )->float :
        contractSize = self.findContractSizeForSymbol( symbol )
        coin = Decimal( (amount * leverage) / (contractSize * price) )
        precision = str(self.findPrecisionForSymbol( symbol ))

        return roundDownTick( coin, precision ) if ( coin > 0 ) else roundUpTick( coin, precision ) 


    def refreshPositions(self, v = verbose):
    ### https://docs.ccxt.com/#/?id=position-structure ###
        failed = False
        try:
            symbols = None
            if( self.exchange.id == 'bitget' ):
                symbols = list(self.markets.keys())
            positions = self.exchange.fetch_positions( symbols, params = {'settle':self.SETTLE_COIN} ) # the 'settle' param is only required by phemex

        except Exception as e:
            a = e.args[0]
            if 'OK' in a: # Coinex raises an exception to give an OK message when there are no positions... don't look at me, look at them
                positions = []
            elif( isinstance(e, ccxt.OnMaintenance) or isinstance(e, ccxt.NetworkError) 
                 or isinstance(e, ccxt.RateLimitExceeded) or isinstance(e, ccxt.RequestTimeout) 
                 or isinstance(e, ccxt.ExchangeNotAvailable) or 'not available' in a ):
                failed = True

                if( 'Remote end closed connection' in a
                   or '500 Internal Server Error' in a
                   or '502 Bad Gateway' in a
                   or 'Internal Server Error' in a
                   or 'Server busy' in a or 'System busy' in a
                   or '"retCode":10002' in a ):
                    print( timeNow(), self.exchange.id, '* E: Refreshpositions:(old)', a, type(e) )
            
            elif( 'Remote end closed connection' in a
                  or '500 Internal Server Error' in a
                  or '502 Bad Gateway' in a
                  or 'Internal Server Error' in a
                  or 'Server busy' in a or 'System busy' in a
                  or 'not available' in a # ccxt.base.errors.ExchangeError
                  or 'failure to get a peer' in a # ccxt.base.errors.ExchangeError (okx)
                  or '"code":39999' in a
                  or '"retCode":10002' in a ):
                failed = True
                # this print is temporary to try to replace the string with the error type if possible
                print( timeNow(), self.exchange.id, '* E: Refreshpositions:', a, type(e) )
            else:
                print( timeNow(), self.exchange.id, '* E: Refreshpositions:', a, type(e) )
                failed = True

        if( failed ):
            self.refreshPositionsFailed += 1
            if( self.refreshPositionsFailed == 10 ):
                print( timeNow(), self.exchange.id, '* W: Refreshpositions has failed 10 times in a row' )
            return
        
        if (self.refreshPositionsFailed >= 10 ):
            print( timeNow(), self.exchange.id, '* W: Refreshpositions has returned to activity' )

        self.refreshPositionsFailed = 0
                    
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
            tab = '  '
            if( numPositions > 0 ) : print('------------------------------')
            # fetch balance
            balanceString = ''
            if SHOW_BALANCE:
                balance = self.fetchBalance()
                balanceString = " Balance: {:.2f}[$]".format(balance['total'])
                balanceString += " - Available {:.2f}[$]".format(balance['free'])
            print( tab + str(numPositions), "positions found.", balanceString )

        self.positionslist.clear()
        for thisPosition in positions:

            symbol = thisPosition.get('symbol')

            # HACK!! bybit response doesn't contain a 'hedge' key, but it contains the information in the 'info' block
            if( self.exchange.id == 'bybit' ):
                thisPosition['hedged'] = True if( thisPosition['info'].get( 'positionIdx' ) != '0' ) else False

            if( self.exchange.id == 'bingx' ): # 'onlyOnePosition': True,
                thisPosition['hedged'] = not thisPosition['info'].get( 'onlyOnePosition' )

            # if the position contains positionMode information update our local data
            if( thisPosition.get('hedged') != None ) : # None means the exchange only supports oneWay
                self.markets[ symbol ]['local'][ 'positionMode' ] = 'hedged' if( thisPosition.get('hedged') == True ) else 'oneway'


            # if the position contains the marginMode information also update the local data

            #some exchanges have the key set to None. Fix it when possible
            if( thisPosition.get('marginMode') == None ) :
                if( self.exchange.id == 'bybit' ): # tradeMode - Classic & UTA (inverse): 0: cross-margin, 1: isolated margin
                    self.markets[ symbol ]['local'][ 'marginMode' ] = 'isolated' if thisPosition['info']['tradeMode'] == '1' else 'cross'
                elif( self.exchange.has.get('setMarginMode') != True ):
                    thisPosition['marginMode'] = MARGIN_MODE_NONE
                else:
                    print( ' * W: refreshPositions: Could not get marginMode for', symbol )
                    thisPosition['marginMode'] = MARGIN_MODE_NONE
            else:
                self.markets[ symbol ]['local'][ 'marginMode' ] = thisPosition.get('marginMode')

            # update the local leverage as well as we can
            leverage = -1
            if( thisPosition.get('leverage') != None ):
                leverage = int(thisPosition.get('leverage'))
                if( leverage != thisPosition.get('leverage') ): # kucoin sends weird fractional leverage. Ignore it
                    leverage = -1

            # still didn't find the leverage, but the exchange has the fetchLeverage method so we can try that.
            if( leverage == -1 and self.exchange.has.get('fetchLeverage') == True ):
                try:
                    response = self.exchange.fetch_leverage( symbol )
                except Exception as e:
                    pass
                else:
                    if( self.exchange.id == 'bitget' ):
                        if( response['data']['marginMode'] == 'crossed' ):
                            leverage = int(response['data'].get('crossMarginLeverage'))
                        else:
                            # they should always be the same
                            longLeverage = int(response['data'].get('fixedLongLeverage'))
                            shortLeverage = int(response['data'].get('fixedShortLeverage'))
                            if( longLeverage == shortLeverage ):
                                leverage = longLeverage

                    elif( self.exchange.id == 'bingx' ):
                        # they should always be the same
                        longLeverage = response['data'].get('longLeverage')
                        shortLeverage = response['data'].get('shortLeverage')
                        if( longLeverage == shortLeverage ):
                            leverage = longLeverage
            
            if( leverage != -1 ):
                self.markets[ symbol ]['local'][ 'leverage' ] = leverage
            elif( self.exchange.id != "kucoinfutures" ): # we know kucoin is helpless
                print( " * W: refreshPositions: Couldn't find leverage for", self.exchange.id )

            self.positionslist.append(position_c( symbol, thisPosition, self.markets[ symbol ] ))

        if v:
            for pos in self.positionslist:
                print( tab + pos.generatePrintString() )

            print('------------------------------')


    def activeOrderForSymbol(self, symbol ):
        for o in self.activeOrders:
            if( o.symbol == symbol ):
                return True
        return False
    

    def fetchClosedOrderById(self, symbol, id ):
        try:
            response = self.exchange.fetch_closed_orders( symbol, params = {'settleCoin':self.SETTLE_COIN} )
        except Exception as e:
            #Exception: ccxt.base.errors.ExchangeError: phemex {"code":39999,"msg":"Please try again.","data":null}
            return None

        for o in response:
            if o.get('id') == id :
                return o
        if verbose : print( "r...", end = '' )
        return None
    

    def fetchOpenOrderById(self, symbol, id ):
        try:
            response = self.exchange.fetch_open_orders( symbol, params = {'settleCoin':self.SETTLE_COIN} )
        except Exception as e:
            #Exception: ccxt.base.errors.ExchangeError: phemex {"code":39999,"msg":"Please try again.","data":null}
            return None

        for o in response:
            if o.get('id') == id :
                return o
        if verbose : print( "r...", end = '' )
        return None
    

    def removeFirstCompletedOrder(self):
        # go through the queue and remove the first completed order
        for order in self.activeOrders:
            if( order.timedOut() ):
                self.print( " * E: Active Order Timed out", order.symbol, order.side, order.quantity, str(order.leverage)+'x' )
                self.activeOrders.remove( order )
                continue

            # Phemex doesn't support fetch_order (by id) in swap mode, but it supports fetch_open_orders and fetch_closed_orders
            if( self.exchange.id == 'phemex' or self.exchange.id == 'bybit' or self.exchange.id == 'krakenfutures' ):
                if( order.type == 'limit' ):
                    response = self.fetchOpenOrderById( order.symbol, order.id )
                else:
                    response = self.fetchClosedOrderById( order.symbol, order.id )
                if( response == None ):
                    continue
            else:
                try:
                    response = self.exchange.fetch_order( order.id, order.symbol )
                except Exception as e:
                    if( isinstance(e, ccxt.InvalidOrder) or 'order not exists' in e.args[0] ):
                        continue

                    self.print( " * E: removeFirstCompletedOrder:", e, type(e) )
                    continue
                
            
            if( response == None ): # FIXME: Check if this is really happening by printing it.
                print( ' * E: removeFirstCompletedOrder: fetch_order returned None' )
                continue
            if( len(response) == 0 ):
                print( ' * E: removeFirstCompletedOrder: fetch_order returned empty' )
                continue
                        
            status = response.get('status')
            remaining = float( response.get('remaining') )
            price = response.get('price')
            if verbose : pprint( response )

            if( order.type == 'limit' ):
                if( self.exchange.id == 'coinex' ) : response['clientOrderId'] = response['info']['client_id'] #HACK!!
                self.print( " * Linmit order placed:", order.symbol, order.side, order.quantity, str(order.leverage)+"x", "at price", price, 'id', response.get('clientOrderId') )
                self.activeOrders.remove( order )
                return True

            if( remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                self.ordersQueue.append( order_c( order.symbol, order.side, remaining, order.leverage, 0.5 ) )
                self.activeOrders.remove( order )
                return True
            
            if ( status == 'closed' or status == 'filled' ):
                self.print( " * Order successful:", order.symbol, order.side, order.quantity, str(order.leverage)+"x", "at price", price, 'id', order.id )
                self.activeOrders.remove( order )
                return True
        return False
    

    def cancelLimitOrder(self, symbol, customID )->bool:
        id = customID
        params = {}
        
        if( self.exchange.id == 'krakenfutures' or self.exchange.id == 'kucoinfutures' or self.exchange.id == 'coinex' or self.exchange.id == 'bitget' ):
            # uuuggggghhhh. why do you do this to me
            try:
                response = self.exchange.fetch_open_orders( symbol, params = {'settleCoin':self.SETTLE_COIN} )
            except Exception as e:
                self.print( ' * E: Unhandled exception in cancelLimitOrder:', e.args[0], type(e) )
                return
            else:
                for o in response:
                    if( ( o['info'].get('cliOrdId') != None and o['info']['cliOrdId'] == customID )
                       or ( o['info'].get('client_id') != None and o['info']['client_id'] == customID )
                        or o['clientOrderId'] == customID ):
                        id = o['id']
        elif( self.exchange.id == 'bybit' ):
            id = None
            params['orderLinkId'] = customID
        elif( self.exchange.id == 'bingx' ):
            id = None
            params['clientOrderID'] = customID
        else:
            params['clientOrderId'] = customID


        try:
            response = self.exchange.cancel_order( id, symbol, params )

        except Exception as e:
            a = e.args[0]
            if( isinstance(e, ccxt.OrderNotFound) or isinstance(e, ccxt.BadRequest)
                or 'order not exists' in a ):
                # ccxt.OrderNotFound: phemex, okx, kraken, binancedemo, bybit
                # ccxt.BadRequest:kucoinfutures The order cannot be canceled
                # coinex: order not exists (and that's all it says)
                self.print( ' * E: Limit order [', customID, '] not found' )
            else:
                self.print( ' * E: cancelLimitOrder:', e.args[0], type(e) )

        else:
            self.print( " * Linmit order [", customID, "] cancelled." )
        return True
    

    def cancelAllOrders(self, symbol )->bool:
            if( self.exchange.has.get('cancelAllOrders') ):
                try:
                    response = self.exchange.cancel_all_orders(symbol)
                except Exception as e:
                    self.print( ' * E: cancelAllOrders:', e.args[0], type(e) )
                    # I've tried cancelling when there were no orders but it reported no error. Maybe I missed something.
                else:
                    self.print( ' * All', symbol, 'orders have been cancelled' )
                return True

            try:
                response = self.exchange.fetch_open_orders( symbol, params = {'settleCoin':self.SETTLE_COIN} )
            except Exception as e:
                self.print( 'cancelAllOrders: No orders found', e.args[0], type(e) )
                return
            
            if( len(response) == 0 ):
                self.print( 'cancelAllOrders: No orders found' )
                return
            
            cancelledCount = 0
            for o in response:
                if( o.get('symbol') == symbol ):
                    try:
                        response = self.exchange.cancel_order( o.get('id'), symbol )
                    except Exception as e:
                        pass
                    else:
                        cancelledCount += 1

            self.print( 'cancelAllOrders:', cancelledCount, 'orders cancelled' )
            return True
                


    def updateOrdersQueue(self):

        # see if any active order was completed and delete it
        while self.removeFirstCompletedOrder():
            continue

        if( len(self.ordersQueue) == 0 ):
            return
        
        # go through the queue activating every symbol that doesn't have an active order
        for order in self.ordersQueue:
            if( self.activeOrderForSymbol(order.symbol) ):
                continue

            if( order.timedOut() ):
                self.print( timeNow(), " * Order Timed out", order.symbol, order.side, order.quantity, str(order.leverage)+'x' )
                self.ordersQueue.remove( order )
                continue

            if( order.delayed() ):
                continue

            # disable hedge mode if present
            self.updateSymbolPositionMode( order.symbol )

            # see if the leverage in the server needs to be changed and set marginMode
            self.updateSymbolLeverage( order.symbol, order.leverage )

            # set up exchange specific parameters
            params = {}

            if( order.reduceOnly ):
                params['reduce'] = True # FIXME Do we need this parameter?
                if( self.exchange.id != 'coinex' ): # coinex interprets reduceOnly as being in hedge mode. Skip the problem by now
                    params['reduceOnly'] = True

            if( self.exchange.id == 'kucoinfutures' ): # Kucoin doesn't use setLeverage nor setMarginMode
                params['leverage'] = max( order.leverage, 1 )
                params['marginMode'] = self.MARGIN_MODE

            if( self.exchange.id == 'krakenfutures' ):
                params['leverage'] = max( order.leverage, 1 )
                params['marginMode'] = self.MARGIN_MODE

            if( self.exchange.id == 'okx' ):
                params['leverage'] = max( order.leverage, 1 )
                params['marginMode'] = self.MARGIN_MODE

            if( self.exchange.id == 'bingx' ):
                if( self.markets[ order.symbol ]['local']['positionMode'] == 'oneway' ):
                    params['positionSide'] = 'BOTH'
                else:
                    params['positionSide'] = 'LONG' if( order.side == "buy" ) else 'SHORT'

            if( order.type == 'limit' ):
                if( self.exchange.id == 'krakenfutures' ):
                    params['cliOrdId'] = order.customID
                elif( self.exchange.id == 'coinex' ):
                    params['client_id'] = order.customID
                elif( self.exchange.id == 'bingx' ):
                    params['clientOrderID'] = order.customID
                else:
                    params['clientOrderId'] = order.customID

            # make sure it's precision adjusted properly
            order.quantity = roundToTick( order.quantity, self.findPrecisionForSymbol(order.symbol) )

            # send the actual order
            try:
                response = self.exchange.create_order( order.symbol, order.type, order.side, order.quantity, order.price, params )
                #pprint( response )

            except Exception as e:
                a = e.args[0]
                
                if( isinstance(e, ccxt.InsufficientFunds) or '"code":"40762"' in a or 'code":101204' in a or '"code":-4131' in a
                   or 'code":101253' in a or 'balance not enough' in a ):
                    # coinex E: Cancelling: balance not enough <class 'ccxt.base.errors.ExchangeError'>
                    # KUCOIN: kucoinfutures Balance insufficient. The order would cost 304.7268292695.
                    # BITGET: {"code":"40754","msg":"balance not enough","requestTime":1689363604542,"data":null}
                    # bitget {"code":"40762","msg":"The order size is greater than the max open size","requestTime":1695925262092,"data":null} <class 'ccxt.base.errors.ExchangeError'>
                    # bingx {"code":101204,"msg":"Insufficient margin","data":{}}
                    # bingx {"code":101253,"msg":"Insufficient margin","data":{}}
                    # phemex {"code":11082,"msg":"TE_CANNOT_COVER_ESTIMATE_ORDER_LOSS","data":null}
                    # phemex {"code":11001,"msg":"TE_NO_ENOUGH_AVAILABLE_BALANCE","data":null}
                    # bybit {"retCode":140007,"retMsg":"remark:order[1643476 23006bb4-630a-4917-af0d-5412aaa1c950] fix price failed for CannotAffordOrderCost.","result":{},"retExtInfo":{},"time":1690540657794}
                    # bybit {"retCode":110007,"retMsg":"Insufficient available balance","result":{},"retExtInfo":{},"
                    # binance "code":-2019,"msg":"Margin is insufficient."
                    # krakenfutures: createOrder failed due to insufficientAvailableFunds
                    # binance {"code":-2027,"msg":"Exceeded the maximum allowable position at current leverage."}
                    # binance {"code":-4131,"msg":"The counterparty's best price does not meet the PERCENT_PRICE filter limit."} <class 'ccxt.base.errors.ExchangeError'>
                    precision = self.findPrecisionForSymbol( order.symbol )
                    # try first reducing it to our estimation of current balance
                    if( not order.reduced ):
                        oldQuantity = order.quantity
                        price = self.fetchSellPrice(order.symbol) if( type == 'sell' ) else self.fetchBuyPrice(order.symbol)
                        available = self.fetchAvailableBalance() * 0.985
                        order.quantity = self.contractsFromUSDT( order.symbol, available, price, order.leverage )
                        order.reduced = True
                        if( order.quantity < self.findMinimumAmountForSymbol(order.symbol) ):
                            self.print( ' * E: Balance insufficient: Minimum contracts required:', self.findMinimumAmountForSymbol(order.symbol), ' Cancelling')
                            self.ordersQueue.remove( order )
                        else:
                            self.print( ' * E: Balance insufficient: Was', oldQuantity, 'Reducing to', order.quantity, "contracts")
                            
                    elif( order.quantity > precision ):
                        if( order.quantity < 20 and precision >= 1 ):
                            self.print( ' * E: Balance insufficient: Reducing by one contract')
                            order.quantity -= precision
                        else:
                            order.quantity = roundDownTick( order.quantity * 0.95, precision )
                            if( order.quantity < self.findMinimumAmountForSymbol(order.symbol) ):
                                self.print( ' * E: Balance insufficient: Cancelling' )
                                self.ordersQueue.remove( order )
                            else:
                                self.print( ' * E: Balance insufficient: Reducing by 5%')

                    else: # cancel the order
                        self.print( ' * E: Balance insufficient: Cancelling' )
                        self.ordersQueue.remove( order )

                    continue # back to the orders loop


                if( isinstance(e, ccxt.InvalidOrder) ):
                    # ERROR Cancelling: okx {"code":"1","data":[{"clOrdId":"001","ordId":"","sCode":"51006","sMsg":"Order price is not within the price limit (Maximum buy price: 26,899.6; minimum sell price: 25,844.6)","tag":""}],"inTime":"1695698840518495","msg":"","outTime":"1695698840518723"}
                    # bitget {"code":"45110","msg":"less than the minimum amount 5 USDT","requestTime":1719060978643,"data":null}
                    if 'Order price is not within' in a:
                        d = json.loads(a.lstrip(self.exchange.id + ' '))
                        self.print( ' * E:', d['data'][0].get('sMsg') )
                        self.ordersQueue.remove( order )
                    elif 'invalidSize' in a or 'code":"45110' in a:
                        self.print( ' * E: Order size invalid:', order.quantity, 'x'+str(order.leverage) )
                        self.ordersQueue.remove( order )
                    elif '"retCode":20094' in a or '"code":-4015' in a or 'ID already exists' in a:
                        self.print( ' * E: Cancelling Linmit order: ID [', order.customID, '] was used before' )
                        self.ordersQueue.remove( order )
                    else:
                        self.print( ' * E: Invalid Order. Cancelling', e )
                        self.ordersQueue.remove( order )
                    
                    continue # back to the orders loop

                #HACK!! this is the shadiest hack ever, but bingx is returning a 'server busy' response
                # when we try to place a limit order with a clientOrderID that has been already used.
                # Basically, he's ghosting us!! It may have found it super offensive.
                if( self.exchange.id == 'bingx' and order.type == 'limit' and '"code":101500' in a ):
                    self.print( ' * E: Cancelling Linmit order: ID [', order.customID, '] was used before' )
                    self.ordersQueue.remove( order )
                    continue
                    

                # bingx {"code":101500,"msg":"The current system is busy, please try again later","data":{}} <class 'ccxt.base.errors.ExchangeError'>
                # bitget {"code":"400172","msg":"The order validity period is invalid","requestTime":1697878512831,"data":null} <class 'ccxt.base.errors.ExchangeError'>
                if( 'Too Many Requests' in a or 'too many request' in a or 'service too busy' in a or 'system is busy' in a ):
                    #set a bigger delay and try again
                    order.delay += 1.0
                    print( type(e) )
                    continue


                # [bitget/bitget] bitget {"code":"45110","msg":"less than the minimum amount 5 USDT","requestTime":1689481837614,"data":null}
                # The deviation between your delegated price and the index price is greater than 20%, you can appropriately adjust your delegation price and try again     
                self.print( ' * E: UpdateOrdersQueue: Unhandled exception. Cancelling:', a, type(e) )
                self.ordersQueue.remove( order )
                continue # back to the orders loop


            if( response.get('id') == None ):
                self.print( " * E: Order denied:", response['info'], "Cancelling" )
                self.ordersQueue.remove( order )
                continue # back to the orders loop

            order.id = response.get('id')
            status = response.get('status')
            remaining = response.get('remaining')
            if( remaining != None and remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                self.ordersQueue.append( order_c( order.symbol, order.side, remaining, order.leverage, 0.5 ) )
                self.ordersQueue.remove( order )
                continue
            if( (remaining == None or remaining == 0) and (response.get('status') == 'closed' or response.get('status') == 'filled') ):
                self.print( " * Order successful:", order.symbol, order.side, order.quantity, str(order.leverage)+"x", "at price", response.get('price'), 'id', order.id )
                self.ordersQueue.remove( order )
                continue

            if verbose : print( timeNow(), " * Activating Order", order.symbol, order.side, order.quantity, str(order.leverage)+'x', 'id', order.id )
            self.activeOrders.append( order )
            self.ordersQueue.remove( order )

    
    def proccessAlert( self, alert:dict ):

        self.print( ' ' )
        self.print( " ALERT:", alert['alert'] )
        self.print('----------------------------')

        # This is our first communication with the server, and (afaik) it will only fail when the server is not available.
        # so we use it as a server availability check as well as for finding the available balance
        try:
            available = self.fetchAvailableBalance() * 0.985
        except Exception as e:
            a = e.args[0]
            if( isinstance(e, ccxt.OnMaintenance) or isinstance(e, ccxt.NetworkError) 
               or isinstance(e, ccxt.RateLimitExceeded) or isinstance(e, ccxt.RequestTimeout) 
               or isinstance(e, ccxt.ExchangeNotAvailable) or 'not available' in a ):
                # ccxt.base.errors.ExchangeError: Service is not available during funding fee settlement. Please try again later.
                if( alert.get('timestamp') + ALERT_TIMEOUT < time.monotonic() ):
                    newAlert = copy.deepcopy( alert ) # the other alert will be deleted
                    if( isinstance(e, ccxt.RateLimitExceeded) ):
                        newAlert['delayTimestamp'] = time.monotonic() + 1
                        self.print( " * E: Rate limit exceeded. Retrying..." )
                    else:
                        newAlert['delayTimestamp'] = time.monotonic() + 30
                        self.print( " * E: Couldn't reach the server: Retrying in 30 seconds", e, type(e) )
                    self.latchedAlerts.append( newAlert )
                else: 
                    self.print( " * E: Couldn't reach the server: Cancelling" )
            else:
                self.print( " * E: Couldn't fetch balance: Cancelling", e, type(e) )
            return

        #
        # TEMP: convert to the old vars. I'll change it later (maybe)
        #
        symbol = alert['symbol']
        command = alert['command']
        quantity = alert['quantity']
        leverage = alert['leverage']
        isUSDT = alert['isUSDT']
        isBaseCurrency = alert['isBaseCurrency']
        isPercentage = alert['isPercentage']
        lockBaseCurrency = alert['lockBaseCurrency']
        priceLimit = alert['priceLimit']
        customID = alert['customID']
        isLimit = True if priceLimit > 0.0 else False


        #time to put the order on the queue
        
        # No point in putting cancel orders in the queue. Just do it and leave.
        if( command == 'cancel' ):
            if( customID == 'all' ):
                self.cancelAllOrders( symbol )
            else:
                self.cancelLimitOrder( symbol, customID )
            return
        
        # bybit is too slow at updating positions after an order is made, so make sure they're updated
        if( self.exchange.id == 'bybit' and (command == 'position' or command == 'close') ):
            self.refreshPositions( False )

        minOrder = self.findMinimumAmountForSymbol(symbol)
        leverage = self.verifyLeverageRange( symbol, leverage )

        # quantity is a percentage of the USDT balance
        if( isPercentage and command != 'close' ):
            quantity = min( max( float(quantity), -100.0 ), 100.0 )
            balance = float( self.fetchBalance().get( 'total' ) )
            quantity = round( balance * quantity * 0.01, 4 )
            isUSDT = True
        
        # convert quantity to concracts if needed
        if( (isUSDT or isBaseCurrency) and quantity != 0.0 ) :
            # We don't know for sure yet if it's a buy or a sell, so we average
            oldQuantity = quantity
            try:
                price = self.fetchAveragePrice(symbol)
                
            except ccxt.ExchangeError as e:
                self.print( " * E: proccessAlert->fetchAveragePrice:", e )
                return
            except ValueError as e:
                self.print( " * E: proccessAlert->fetchAveragePrice", e, type(e) )
                return
                
            coin_name = self.markets[symbol]['quote']
            if( isBaseCurrency ) :
                if( lockBaseCurrency and leverage > 1 ):
                    quantity = quantity * price / leverage
                else:
                    quantity *= price

                coin_name = self.markets[symbol]['base']

            quantity = self.contractsFromUSDT( symbol, quantity, price, leverage )
            if verbose : print( "   CONVERTING (x"+str(leverage)+")", oldQuantity, coin_name, '==>', quantity, "contracts" )
            if( abs(quantity) < minOrder ):
                self.print( timeNow(), " * E: Order too small:", quantity, "Minimum required:", minOrder )
                return

        # check for a existing position
        pos = self.getPositionBySymbol( symbol )

        if( command == 'close' or (command == 'position' and quantity == 0) ):
            if pos == None:
                self.print( timeNow(), " * 'Close", symbol, "' No position found" )
                return
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )

            if( command == 'close' and isPercentage ):
                quantity = min( abs(quantity), 100.0 )
                positionContracts = positionContracts * quantity * 0.01


            if( positionSide == 'long' ):
                self.ordersQueue.append( order_c( symbol, 'sell', positionContracts, 0 ) )
            else: 
                self.ordersQueue.append( order_c( symbol, 'buy', positionContracts, 0 ) )

            return
        
        # position orders are absolute. Convert them to buy/sell order
        if( command == 'position' ):
            if( pos == None or pos.getKey('contracts') == None ):
                # it's just a straight up buy or sell
                if( quantity < 0 ):
                    command = 'sell'
                else:
                    command = 'buy'
                quantity = abs(quantity)
            elif( self.markets[symbol]['local']['marginMode'] != self.MARGIN_MODE and self.exchange.has['setMarginMode'] ):
                # to change marginMode we need to close the old position first
                if( pos.getKey('side') == 'long' ):
                    self.ordersQueue.append( order_c( symbol, 'sell', pos.getKey('contracts'), 0 ) )
                else: 
                    self.ordersQueue.append( order_c( symbol, 'buy', pos.getKey('contracts'), 0 ) )
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
                    self.print( " * Order completed: Request matched current position")
                    return
            # fall through


        if( command == 'buy' or command == 'sell'):

            # fetch available balance and price
            price = self.fetchSellPrice(symbol) if( command == 'sell' ) else self.fetchBuyPrice(symbol)
            canDoContracts = self.contractsFromUSDT( symbol, available, price, leverage )

            if( pos != None ):
                positionContracts = pos.getKey('contracts')
                positionSide = pos.getKey( 'side' )
                
                # reversing the position
                if not isLimit and (( positionSide == 'long' and command == 'sell' ) or ( positionSide == 'short' and command == 'buy' )):

                    # do we need to divide these in 2 orders?

                    # bingx must make one order for close and a second one for the new position
                    if( self.exchange.id == 'bingx' ):
                        if( quantity > positionContracts ):
                            self.ordersQueue.append( order_c( symbol, command, positionContracts, 0 ) )
                            quantity -= positionContracts
                            self.ordersQueue.append( order_c( symbol, command, quantity, leverage ) )
                            return
                        
                        self.ordersQueue.append( order_c( symbol, command, quantity, leverage, reduceOnly=True ) )
                        return
                    
                    # FIXME: Bybit takes the fees on top of the order which makes it fail with insuficcient
                    # balance when we try to order all the balance at once, which creates complications
                    # when reducing a reveral order. This is a temporary way to make it work, but 
                    # we should really calculate the fees
                    #
                    # FIXME: Temporarily using this path for OKX too
                    if( ( self.exchange.id == 'bybit' or self.exchange.id == 'okx' ) and quantity > positionContracts ):
                        self.ordersQueue.append( order_c( symbol, command, positionContracts, 0, reduceOnly = True ) )
                        quantity -= positionContracts
                        if( quantity > minOrder ):
                            self.ordersQueue.append( order_c( symbol, command, quantity, leverage ) )
                        return

                    if( quantity >= canDoContracts + positionContracts ):
                        # we have to make sure each of the orders has the minimum order contracts
                        order1 = canDoContracts + positionContracts
                        order2 = quantity - (canDoContracts + positionContracts)
                        if( order2 < minOrder ):
                            diff = minOrder - order2
                            if( order1 > minOrder + diff ):
                                order1 -= diff

                        # first order is the contracts in the position and the contracs we can afford with the liquidity
                        self.ordersQueue.append( order_c( symbol, command, order1, leverage ) )

                        # second order is whatever we can afford with the former position contracts + the change
                        quantity -= order1
                        if( quantity >= minOrder ): #we are done (should never happen)
                            self.ordersQueue.append( order_c( symbol, command, quantity, leverage, 1.0 ) )

                        return
                # fall through

            if( quantity < minOrder ):
                self.print( timeNow(), " * E: Order too small:", quantity, "Minimum required:", minOrder )
                return

            order = order_c( symbol, command, quantity, leverage )
            if( isLimit ):
                order.type = 'limit'
                order.customID = customID
                order.price = priceLimit

            self.ordersQueue.append( order )
            return

        self.print( " * E: Something went wrong. No order was placed")


accounts = []




def stringToValue( arg )->float:
    try:
        float(arg)
    except ValueError:
        value = None
    else:
        value = float(arg)
    return value


def updateOrdersQueue():
    for account in accounts:
        numOrders = len(account.ordersQueue) + len(account.activeOrders)
        account.updateOrdersQueue()

        # see if we have any alert pending to be proccessed
        if( len(account.latchedAlerts) ):
            positionsRefreshed = False
            for alert in account.latchedAlerts:
                if( alert.get('delayTimestamp') != None ):
                    alert.get('delayTimestamp') < time.monotonic()
                    continue

                busy = False
                for order in account.activeOrders:
                    if( order.symbol == alert['symbol'] ):
                        busy = True
                        break
                for order in account.ordersQueue:
                    if( order.symbol == alert['symbol'] ):
                        busy = True
                        break
                
                if( not busy ):
                    if( not positionsRefreshed ):
                        account.refreshPositions(False)
                        positionsRefreshed = True

                    account.proccessAlert( alert )
                    account.latchedAlerts.remove( alert )

        # if we just cleared the orders queue refresh the positions info
        if( numOrders > 0 and (len(account.ordersQueue) + len(account.activeOrders)) == 0 ):
            account.refreshPositions(True)


def refreshPositions():
    for account in accounts:
        account.refreshPositions()


def generatePositionsString()->str:
    msg = ''
    for account in accounts:
        account.refreshPositions()
        numPositions = len(account.positionslist)
        balanceString = ''
        if SHOW_BALANCE:
            balance = account.fetchBalance()
            balanceString = " * Balance: {:.2f}[$]".format(balance['total'])
            balanceString += " - Available {:.2f}[$]".format(balance['free'])
        msg += '---------------------\n'
        msg += 'Refreshing positions '+account.accountName+': ' + str(numPositions) + ' positions found' + balanceString + '\n'
        if( numPositions == 0 ):
            continue

        for pos in account.positionslist:
            msg += pos.generatePrintString() + '\n'

    return msg

def parseAlert( data, account: account_c ):

    if( account == None ):
        return { 'Error': " * E: parseAlert called without an account" }
    
    alert = {
        'symbol': None,
        'command': None,
        'quantity': None,
        'leverage': 0,
        'isUSDT': False,
        'isBaseCurrency': False,
        'isPercentage': False,
        'lockBaseCurrency': False,
        'priceLimit': 0.0,
        'customID': None,
        'alert': data,
        'timestamp':time.monotonic()
    }

    limitToken = None
    cancelToken = None

    # Informal plain text syntax
    tokens = data.split()
    for token in tokens:
        if( account.findSymbolFromPairName(token) != None ): # GMXUSDTM, GMX/USDT:USDT and GMX/USDT are all acceptable formats
            alert['symbol'] = account.findSymbolFromPairName(token) 
        elif ( token == account.accountName ):
            pass
        elif ( token[-1:]  == "$" ): # value in USDT
            alert['isUSDT'] = True
            arg = token[:-1]
            alert['quantity'] = stringToValue( arg )
        elif ( token[-1:]  == "@" ): # value in contracts
            arg = token[:-1]
            alert['quantity'] = stringToValue( arg )
        elif ( token[-1:]  == "%" ): # value in percentage of balance
            arg = token[:-1]
            alert['quantity'] = stringToValue( arg )
            alert['isPercentage'] = True
        elif ( token[:1]  == "-" ): # this is a minus symbol! What a bitch (value in base currency)
            alert['isBaseCurrency'] = True
            alert['quantity'] = stringToValue( token )
        elif ( stringToValue( token ) != None ):
            alert['isBaseCurrency'] = True
            arg = token
            alert['quantity'] = stringToValue(arg)
        elif token.lower()  == 'force_usdt':
            alert['isUSDT'] = True
        elif token.lower()  == 'force_percent':
            alert['isPercentage'] = True
        elif token.lower()  == 'force_basecurrency':
            alert['isBaseCurrency'] = True
        elif token.lower()  == 'lockbasecurrency' or token.lower() == "bclock":
            alert['lockBaseCurrency'] = True
        elif ( token[:1].lower()  == "x" ):
            arg = token[1:]
            alert['leverage'] = int(stringToValue(arg))
        elif ( token[-1:].lower()  == "x" ):
            arg = token[:-1]
            alert['leverage'] = int(stringToValue(arg))
        elif token.lower()  == 'long':
            alert['command'] = 'buy'
            print( "WARNING: 'long' and 'short' commands are deprecated and will be removed in the future. Please use 'buy' and 'sell' instead" )
        elif token.lower()  == 'short':
            alert['command'] = 'sell'
            print( "WARNING: 'long' and 'short' commands are deprecated and will be removed in the future. Please use 'buy' and 'sell' instead" )
        elif token.lower() == "buy":
            alert['command'] = 'buy'
        elif token.lower() == "sell":
            alert['command'] = 'sell'
        elif token.lower()  == 'close':
            alert['command'] = 'close'
        elif token.lower()  == 'position' or token.lower()  == 'pos':
            alert['command'] = 'position'
        elif ( token[:5].lower()  == "limit" ):
            limitToken = token # we validate it at processing
        elif ( token[:6].lower()  == "cancel" ):
            cancelToken = token # we validate it at processing
            alert['command'] = 'cancel'
    
    # do some syntax validation
    if( alert['symbol'] == None ):
        return { 'Error': " * E: Couldn't find symbol" }
    
    if( alert['command'] == None ):
        return { 'Error': " * E: Invalid Order: Missing command" }
    
    if( alert['command'] == 'buy' or alert['command'] == 'sell' or alert['command'] == 'position' ):
        if( alert['quantity'] == None ):
            return { 'Error': " * E: Invalid quantity value" }
        if( alert['quantity'] < 0 and alert['command'] == 'buy' ):
            return { 'Error': " * E: Invalid Order: Buy must have a positive amount" }
        if( alert['quantity'] == 0 and alert['command'] != 'position' ):
            return { 'Error':" * E: Invalid Order amount: 0" }
        if( alert['command'] == 'sell' and alert['quantity'] < 0 ): # be flexible with sell having a negative amount
            alert['quantity'] = abs(alert['quantity'])
    
    # parse de cancel and limit tokens
    if( limitToken != None ):
        if( alert['command'] != 'buy' and alert['command'] != 'sell' ):
            return { 'Error': " * E: Limit orders can only be used with buy/sell commands" }

        v = limitToken.split(':')
        if( len(v) != 3 ):
            return { 'Error': " * E: Limit command must be formatted as 'limit:customID:price' " }
        else:
            alert['customID'] = v[1]
            alert['priceLimit'] = stringToValue(v[2])
            if( alert['priceLimit'] == None ):
                return { 'Error': " * E: Limit command must be formatted as 'limit:customID:price' " }
            if( alert['priceLimit'] <= 0 ):
                return { 'Error': " * E: price limit must be bigger than 0" }
    
    if ( cancelToken != None ):
        v = cancelToken.split(':')
        if( len(v) != 2 ):
            return { 'Error': " * E: Cancel command must be formatted as 'cancel:customID' " }
        alert['customID'] = v[1]

    if( alert['customID'] != None ):
        if( len(alert['customID']) < 2 or len(alert['customID']) > 30 ):
            return { 'Error': " * E: customID must be longer than 2 characters and shorter than 30' " }
        if( account.exchange.id == 'coinex' and not alert['customID'].isdigit() ):
            return { 'Error': " * E: Coinex only accepts numeric customID' " }

    if verbose : print( alert )
    return alert



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
            print( timeNow(), ' * E: Account ID not found. ALERT:', line )
            telegramAdminMsg( 'Account ID not found. ALERT:', line )
            continue
        
        alert = parseAlert( line.replace('\n', ''), account )
        if( alert.get('Error') != None ):
            account.print( ' ' )
            account.print( " ALERT:", line.replace('\n', '') )
            account.print('----------------------------')
            account.print( alert.get('Error') )
            continue

        # check if the alert can be proccessed inmediately
        busy = False
        for o in account.activeOrders:
            if( o.symbol == alert['symbol'] ):
                busy = True
                break
        for o in account.ordersQueue:
            if( o.symbol == alert['symbol'] ):
                busy = True
                break
        
        if( not busy ):
            account.proccessAlert( alert )
            continue
        
        # delay the alert proccessing
        account.latchedAlerts.append( alert )

def telegramCommand( message ):
    if( message[:1] == '/' ):
        message = message[1:]
    tokens = message.split()
    if( tokens[0].lower() == 'balance' ):
        if( len(tokens) == 1 ): # all accounts
            msg = ''
            for a in accounts:
                msg += a.accountName + '\n'
                msg += "Total: {:.2f}\n".format(a.fetchBalance().get('total'))

            if( len(msg) == '0' ):
                msg = 'No accounts found'
            else:
                telegramAdminMsg( msg )
            return
        
        # specific account requested
        account = None
        for token in tokens:
            for a in accounts:
                if( token == a.accountName ):
                    account = a
                    break
        if( account == None ):
            telegramAdminMsg( "Account not found" )
        else:
            telegramAdminMsg( "Total: {:.2f}\n".format(a.fetchBalance().get('total')) )
        return
    
    if( tokens[0].lower() == 'positions' ):
        if( len(tokens) == 1 ): # all accounts
            if( len(accounts) == '0' ):
                telegramAdminMsg( 'No accounts found' )
            else:
                telegramAdminMsg( generatePositionsString() )
            return
        
        # specific account requested
        account = None
        for token in tokens:
            for a in accounts:
                if( token == a.accountName ):
                    account = a
                    break
        if( account == None ):
            telegramAdminMsg( "Account not found" )
        else:
            msg = ''
            account.refreshPositions()
            numPositions = len(account.positionslist)
            msg += '---------------------\n'
            msg += 'Refreshing positions '+account.accountName+': ' + str(numPositions) + ' positions found\n'
            if( numPositions > 0 ):
                for pos in account.positionslist:
                    msg += pos.generatePrintString() + '\n'

            telegramAdminMsg( msg )
        return

    telegramAdminMsg( "unknown command." )


###################
#### Initialize ###
###################

print('----------------------------')

#### Open accounts file ###

try:
    with open('accounts.json', 'r') as accounts_file:
        accounts_data = json.load(accounts_file)
        accounts_file.close()
except FileNotFoundError:
    with open('accounts.json', 'x') as f:
        f.write( '[\n\t{\n\t\t"ACCOUNT_ID":"your_account_name", \n\t\t"EXCHANGE":"exchange_name", \n\t\t"API_KEY":"your_api_key", \n\t\t"SECRET_KEY":"your_secret_key", \n\t\t"PASSWORD":"your_API_password", \n\t\t"MARGIN_MODE":"isolated"\n\t}\n]' )
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

    marginMode = ac.get('MARGIN_MODE')

    settleCoin = ac.get('SETTLE_COIN')

    print( timeNow(), " Initializing account: [", account_id, "] in [", exchange , ']')
    try:
        account = account_c( exchange, account_id, api_key, secret_key, password, marginMode, settleCoin )
    except Exception as e:
        print( 'Account creation failed:', e, type(e) )
        print('------------------------------')
    else:
        accounts.append( account )

if( len(accounts) == 0 ):
    print( " * FATAL ERROR: No valid accounts found. Please edit 'accounts.json' and introduce your API keys" )
    raise SystemExit()

telegramAdminMsg( 'Whook started.' )

############################################

# define the webhook server
app = Flask(__name__)
# silencing flask useless spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.disabled = True

if USE_PROXY == True:
    # warn Flask that we are behind a Web proxy
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )
    PORT = PROXY_PORT

@app.route('/whook', methods=['GET','POST'])
def webhook():

    if request.method == 'POST':
        content_type = request.headers.get('Content-Type')
        if content_type == 'application/json':
            data = request.get_json()

            if data and 'update_id' in data:  # Typical key in Telegram bot updates

                # Extract message text and chat ID
                if 'message' in data:
                    chat_id = data['message']['chat']['id']
                    message = data['message']['text']
                    
                    # Log the received message
                    #print( "Received message from chat_id", chat_id, ':', message )

                    if( message[:1] == '/' and message[:2] != '//' ): # / is a command // is alert comments
                        telegramCommand( message )
                    else:
                        telegramAdminMsg( "Posting alert.")
                        Alert( message ) # try to proccess it as an alert

                return 'Telegram message processed', 200

            # we received a json but apparently it's not from telegram
            return 'success', 200
        
        # Standard alert
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
    app.run(host="0.0.0.0", port=PORT, debug=False)


