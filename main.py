

import ccxt
from flask import Flask, request, abort
from threading import Timer
import time
from datetime import datetime
import json
import logging
#import csv

verbose = False
_ORDER_TIMEOUT_ = 10

today = datetime.today()

year = today.year
month = today.month
day = today.day
#print("Current year:", today.year)
#print("Current month:", today.month)
#print("Current day:", today.day)
#print("Hour =", today.hour)
#print("Minute =", today.minute)
#print("Second =", today.second )

def timeNow():
    return time.strftime("%H:%M:%S")

def dateString():
    return datetime.today().strftime("%Y/%m/%d")

# create logger PNL
#pnllogger = logging.getLogger('balance')
#fh = logging.FileHandler('balance.log')
#pnllogger.addHandler( fh )
#pnllogger.level = logging.INFO

# create logger for trades
logger = logging.getLogger('webhook')
fh = logging.FileHandler('webhook.log')
logger.addHandler( fh )
logger.level = logging.INFO

def printf(*args, sep=" ", **kwargs):
    logger.info( dateString()+sep.join(map(str,args)), **kwargs)
    print( ""+sep.join(map(str,args)), **kwargs)

class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)

class position_c:
    def __init__(self, symbol, position) -> None:
        self.symbol = symbol
        self.position = position
    def getKey(cls, key):
        return cls.position.get(key)

class order_c:
    def __init__(self, symbol = "", type = "", quantity = 0.0, leverage = 1, delay = 0) -> None:
        self.type = type
        self.symbol = symbol
        self.quantity = quantity
        self.leverage = leverage
        self.reduced = False
        self.id = ""
        self.delay = delay
        self.timestamp = time.monotonic()
    def setType(cls, type):
        cls.type = type
    def setSymbol(cls, symbol):
        cls.symbol = symbol
    def setLeverage(cls, leverage):
        cls.leverage = int(leverage)
    def setQuantity(cls, quantity):
        cls.quantity = int(quantity)
    def timedOut(cls):
        return ( cls.timestamp + _ORDER_TIMEOUT_ < time.monotonic() )
    def delayed(cls):
        return (cls.timestamp + cls.delay > time.monotonic() )

class account_c:
    def __init__(self, exchange = None, name = 'default', apiKey = None, secret = None, password = None )->None:
        if( name.isnumeric() ):
            printf( " * FATAL ERROR: Account 'id' can not be only  numeric" )
            raise SystemExit()
        
        self.accountName = name
        self.positionslist = []
        self.ordersQueue = []
        self.activeOrders = []
        if( exchange == None ):
            printf( " * FATAL ERROR: No exchange was resquested" )
            raise SystemExit()
        
        if( exchange.lower() == 'kucoinfutures' ):
            self.exchange = ccxt.kucoinfutures( {
                'apiKey': apiKey,
                'secret': secret,
                'password': password,
                #'enableRateLimit': True
                } )
                #self.exchange.rateLimit = 333
        elif( exchange.lower() == 'bitget' ):
            self.exchange = ccxt.bitget({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            # self.exchange.set_sandbox_mode( True )
            #print( self.exchange.set_position_mode( False ) )
        else:
            printf( " * FATAL ERROR: Unsupported exchange:", exchange )
            raise SystemExit()

        if( self.exchange == None ):
            printf( " * FATAL ERROR: Exchange creation failed" )
            raise SystemExit()
        
        self.markets = self.exchange.load_markets()
        self.balance = self.fetchBalance()
        print( self.balance )
        self.refreshPositions(True)

    #methods
    def fetchBalance(cls):
        response = cls.exchange.fetch_balance()
        return response.get('USDT')
    
    def fetchAvailableBalance(cls)->float:
        available = cls.exchange.fetch_free_balance()['USDT']
        return available
    
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
        #first let's check if the pair string contains
        #a backslash. If it does it's probably already a symbol
        #but it also may not include the ':USDT' ending
        if '/' not in paircmd and paircmd.endswith('USDT'):
            paircmd = paircmd[:-4]
            paircmd += '/USDT:USDT'

        if '/' in paircmd and not paircmd.endswith(':USDT'):
            paircmd += ':USDT'

        #try the more direct approach
        m = cls.markets.get(paircmd)
        if( m != None ):
            return m.get('symbol')

        #so now let's find it in the list using the id
        for m in cls.markets:
            id = cls.markets[m]['id'] 
            symbol = cls.markets[m]['symbol']
            if( symbol == paircmd or id == paircmd ):
                return symbol
        return None
    
    def findContractSizeForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m != None ):
            return m.get('contractSize')
        return None
    
    def findPrecisionForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m != None ):
            p = m.get('precision')
            if( p != None ):
                return p.get('amount')
        return 1.0
    
    def findMinimumAmountForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m != None ):
            l = m.get('limits')
            if( l != None ):
                a = l.get('amount')
                if( a != None ):
                    return a.get('min')
        return 1.0
    
    def findMaxLeverageForSymbol(cls, symbol)->float:
        #'leverage': {'min': 1.0, 'max': 50.0}}
        m = cls.markets.get(symbol)
        if( m != None ):
            bounds = m['limits']['leverage']
            maxLeverage = bounds['max']
            return maxLeverage
        return None
    
    def contractsFromUSDT(cls, symbol, amount, price, leverage = 1.0 )->float :
        contractSize = cls.findContractSizeForSymbol( symbol )
        precision = cls.findPrecisionForSymbol( symbol )
        coin = (amount * leverage) / (contractSize * price)
        return roundDownTick( coin, precision ) if ( coin > 0 ) else roundUpTick( coin, precision )
        
    def refreshPositions(cls, v = verbose):
    ### https://docs.ccxt.com/#/?id=position-structure ###
        try:
            positions = cls.exchange.fetch_positions()
        except Exception as e:
            for a in e.args:
                if 'Remote end closed connection' in a :
                    printf( timeNow, ' * Exception raised: Refreshpositions. Remote end closed connection' )
                elif '502 Bad Gateway' in a:
                    printf( timeNow, ' * Exception raised: 502 Bad Gateway' )
                else:
                    printf( timeNow, ' * Unknown Exception raised: Refreshpositions:', a )
            return
                    
        numPositions = len(positions)
        if v:
            if( numPositions > 0 ) : print('------------------------------')
            print('Refreshing positions '+cls.accountName+':', numPositions, "positions found" )
            
        cls.positionslist.clear()
        for element in positions:
            thisPosition = cls.exchange.parse_positions( element )[0]
            #symbol = thisPosition['symbol']
            symbol = thisPosition.get('symbol')
            cls.positionslist.append(position_c( symbol, thisPosition ))

        if v:
            for pos in cls.positionslist:
                p = ( pos.getKey('unrealizedPnl') / pos.getKey('initialMargin') ) * 100.0
                print(pos.symbol, pos.getKey('side'), pos.getKey('contracts'), pos.getKey('collateral'), pos.getKey('unrealizedPnl'), "{:.2f}".format(p) + '%', sep=' * ')
        
        if v : print('------------------------------')

    def activeOrderForSymbol(cls, symbol ):
        for o in cls.activeOrders:
            if( o.symbol == symbol ):
                return True
        return False
    
    def removeFirstCompletedOrder(cls):
        # go through the queue and remove the first completed order
        for order in cls.activeOrders:
            if( order.timedOut() ):
                printf( timeNow(), " * Active Order Timed out", order.symbol, order.type, order.quantity, str(order.leverage)+'x' )
                cls.activeOrders.remove( order )
                continue

            info = cls.exchange.fetch_order( order.id, order.symbol )
            status = info.get('status')
            remaining = int( info.get('remaining') )
            price = info.get('price')
            if verbose : print( status, 'remaining:', remaining, 'price:', price )

            if( remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                cls.ordersQueue.append( order_c( order.symbol, order.type, remaining, order.leverage, 0.5 ) )
                cls.activeOrders.remove( order )
                return True
            
            if ( status == 'closed' ):
                printf( timeNow(), "* Order succesful:", order.symbol, order.type, order.quantity, str(order.leverage)+"x", "at price", price, 'id', order.id )
                order.quantity = 0
                order.leverage = 0
                cls.activeOrders.remove( order )
                return True
        return False

    def updateOrdersQueue(cls):

        numOrders = len(cls.ordersQueue) + len(cls.activeOrders)

        #see if any active order was completed and delete it
        while cls.removeFirstCompletedOrder():
            continue

        #if we just cleared the orders queue refresh the positions info
        if( numOrders > 0 and (len(cls.ordersQueue) + len(cls.activeOrders)) == 0 ):
            cls.refreshPositions(True)

        if( len(cls.ordersQueue) == 0 ):
            return
        
        # go through the queue activating every symbol that doesn't have an active order
        for order in cls.ordersQueue:
            if( cls.activeOrderForSymbol(order.symbol) ):
                continue

            if( order.timedOut() ):
                printf( timeNow(), " * Order Timed out", order.symbol, order.type, order.quantity, str(order.leverage)+'x' )
                cls.ordersQueue.remove( order )
                continue

            if( order.delayed() ):
                continue

            params = {}

            if( cls.exchange.id == 'kucoinfutures' ):
                params['leverage'] = order.leverage

            if( cls.exchange.id == 'bitget' ):
                try: #disable hedged mode
                    response = cls.exchange.set_position_mode( False, order.symbol )
                    params['side'] = 'buy_single' if( order.type == "buy" ) else 'sell_single'
                except Exception as e:
                    print( timeNow(), " * Exception Raised. Failed to set position mode:", e )

                try: #set leverage
                    response = cls.exchange.set_leverage( order.leverage, order.symbol )
                except Exception as e:
                    print( timeNow(), " * Exception Raised. Failed to set leverage:", e )

            # send the actual order
            try:
                response = cls.exchange.create_market_order( order.symbol, order.type, order.quantity, None, params )
                #print( response )
            
            except Exception as e:
                print( e.args )
                for a in e.args:
                    if 'Too Many Requests' in a : #set a bigger delay and try again
                        order.delay += 0.5
                        break
                    elif 'Balance insufficient' in a :
                        precision = cls.findPrecisionForSymbol( order.symbol )
                        # try first reducing it to our estimation of current balance
                        if( not order.reduced ):
                            price = cls.fetchSellPrice(order.symbol) if( type == 'sell' ) else cls.fetchBuyPrice(order.symbol)
                            available = cls.fetchAvailableBalance() * 0.985
                            order.quantity = cls.contractsFromUSDT( order.symbol, available, price, order.leverage )
                            order.reduced = True
                            if( order.quantity < cls.findMinimumAmountForSymbol(order.symbol) ):
                                printf( ' * Exception raised: Balance insufficient (', available,'): Cero contracts possible. Cancelling')
                                cls.ordersQueue.remove( order )
                            else:
                                printf( ' * Exception raised: Balance insufficient: Reducing to', order.quantity, "contracts")
                                
                            break
                        elif( order.quantity > precision ):
                            if( order.quantity < 20 and precision >= 1 ):
                                printf( ' * Exception raised: Balance insufficient: Reducing by one contract')
                                order.quantity -= precision
                            else:
                                order.quantity = roundDownTick( order.quantity * 0.95, precision )
                                if( order.quantity < cls.findMinimumAmountForSymbol(order.symbol) ):
                                    printf( ' * Exception raised: Balance insufficient: Cancelling' )
                                    cls.ordersQueue.remove( order )
                                else:
                                    printf( ' * Exception raised: Balance insufficient: Reducing by 5%')
                            break
                        else: #cancel the order
                            printf( ' * Exception raised: Balance insufficient: Cancelling')
                            cls.ordersQueue.remove( order )
                            break
                    else: #Unknown exception raised
                        printf( ' * ERROR Cancelling: Unhandled Exception raised:', e )
                        cls.ordersQueue.remove( order )
                        break
                continue #back to the orders loop

            if( response.get('id') == None ):
                print( "Order denied:", response['info'], "Cancelling" )
                cls.ordersQueue.remove( order )
                continue
            
            order.id = response.get('id')
            if verbose : print( timeNow(), " * Activating Order", order.symbol, order.type, order.quantity, str(order.leverage)+'x', 'id', order.id )
            cls.activeOrders.append( order )
            cls.ordersQueue.remove( order )

accounts = []


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

def stringToValue( arg )->float:
    if (arg[:1] == "-" ): # this is a minus symbol! What a bitch
        arg = arg[1:]
        return -float(arg)
    else:
        return float(arg)

def is_json( j ):
    try:
        json.loads( j )
    except ValueError as e:
        return False
    return True

# def contractsFromUSDT( amount, contractSize, precision, price, leverage = 1.0 )->float :
#     coin = (amount * leverage) / (contractSize * price)
#     return roundDownTick( coin, precision ) if ( coin > 0 ) else roundUpTick( coin, precision )

def updateOrdersQueue():
    for account in accounts:
        account.updateOrdersQueue()

def refreshPositions():
    for account in accounts:
        account.refreshPositions()

def parseAlert( data, isJSON, account: account_c ):

    if( account == None ):
        printf( timeNow(), " * ERROR: parseAlert called without an account" )
        return

    symbol = "Invalid"
    quantity = 0
    leverage = 0
    type = "Invalid"
    isUSDT = False

    # FIXME: json commands are pretty incomplete because I don't use them
    if( isJSON ):
        jdata = json.loads(data)
        for key, value in jdata.items():
            if key == 'ticker' or key == 'symbol':
                if( account.findSymbolFromPairName(value) != None ): # GMXUSDTM, GMX/USDT:USDT and GMX/USDT are all acceptable formats
                    symbol = account.findSymbolFromPairName(value) 
            elif key == 'action' or key == 'command':
                type = value
            elif key == 'quantity':
                quantity = int(value)
            elif key == 'leverage':
                leverage = int(value)
    else:
        # Informal plain text syntax
        tokens = data.split()
        for token in tokens:
            if( account.findSymbolFromPairName(token) != None ): # GMXUSDTM, GMX/USDT:USDT and GMX/USDT are all acceptable formats
                symbol = account.findSymbolFromPairName(token) 
            elif ( token[-1:]  == "$" ):
                isUSDT = True
                arg = token[:-1]
                quantity = stringToValue( arg )
            elif ( token[:1]  == "-" ): # this is a minus symbol! What a bitch
                quantity = stringToValue( token )
            elif ( token.isnumeric() ):
                arg = token
                quantity = int(arg)
            elif ( token[:1].lower()  == "x" ):
                arg = token[1:]
                leverage = int(arg)
            elif ( token[-1:].lower()  == "x" ):
                arg = token[:-1]
                leverage = int(arg)
            elif token.lower()  == 'long' or token.lower() == "buy":
                type = 'buy'
            elif token.lower()  == 'short' or token.lower() == "sell":
                type = 'sell'
            elif token.lower()  == 'close':
                type = 'close'
            elif token.lower()  == 'position' or token.lower()  == 'pos':
                type = 'position'
    

    #let's try to validate the commands
    if( symbol == "Invalid"):
        printf( "ERROR: Couldn't find symbol" )
        return
    if( type == "Invalid" ):
        printf( "Invalid Order: Missing command")
        return 
    if( quantity <= 0 and (type == 'buy' or type == 'sell') ):
        printf( "Invalid Order: Buy/Sell must have positive amount")
        return

    #time to put the order on the queue

    maxLeverage = account.findMaxLeverageForSymbol( symbol )
    leverage = max( leverage, 1 )
    if( maxLeverage != None and maxLeverage < leverage ):
        printf( " * WARNING: Leverage out of bounds. Readjusting to", str(maxLeverage)+"x" )
        leverage = maxLeverage

    contractSize = account.findContractSizeForSymbol(symbol)
    precision = account.findPrecisionForSymbol( symbol )
    available = account.fetchAvailableBalance() * 0.985
    
    # convert quantity to concracts if needed
    if( isUSDT ) :
        print( "CONVERTING", quantity, "$ - Leverage", leverage, end = '' )
        #We don't know for sure yet if it's a buy or a sell, so we average
        quantity = account.contractsFromUSDT( symbol, quantity, account.fetchAveragePrice(symbol), leverage )
        print( ":", quantity, "contracts" )
        

    #check for a existing position
    pos = account.getPositionBySymbol( symbol )

    if( type == 'close' or (type == 'position' and quantity == 0) ):
        if pos == None:
            printf( timeNow(), " * 'Close", symbol, "' No position found" )
            return
        positionContracts = pos.getKey('contracts')
        positionSide = pos.getKey( 'side' )
        if( positionSide == 'long' ):
            account.ordersQueue.append( order_c( symbol, 'sell', positionContracts, 1 ) )
        else: 
            account.ordersQueue.append( order_c( symbol, 'buy', positionContracts, 1 ) )

        return
    
    # position orders are absolute. Convert them to buy/sell order
    if( type == 'position' ):
        if( pos == None ):
            # it's just a straight up buy or sell
            if( quantity < 0 ):
                type = 'sell'
            else:
                type = 'buy'
            quantity = abs(quantity)
        else:
            #we need to account for the old position
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )
            if( positionSide == 'short' ):
                positionContracts = -positionContracts

            type = 'sell' if positionContracts > quantity else 'buy'
            quantity = abs( quantity - positionContracts )
            if( quantity == 0 ):
                printf( " * Order completed: Request matched current position")
                return
        # fall through


    if( type == 'buy' or type == 'sell'):

        #fetch available balance and price
        price = account.fetchSellPrice(symbol) if( type == 'sell' ) else account.fetchBuyPrice(symbol)
        canDoContracts = account.contractsFromUSDT( symbol, available, price, leverage )
        
        if verbose : print( "CandoContracts", canDoContracts )

        if( pos != None ):
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )
            
            if ( positionSide == 'long' and type == 'sell' ) or ( positionSide == 'short' and type == 'buy' ):
                # de we need to divide these in 2 orders?
                if( quantity >= canDoContracts + positionContracts ):
                    #first order is the contracts in the position and the contracs we can afford with the liquidity
                    account.ordersQueue.append( order_c( symbol, type, canDoContracts + positionContracts, leverage ) )

                    #second order is whatever we can affort with the former position contracts + the change
                    quantity -= canDoContracts + positionContracts
                    if( quantity < 1 ): #we are done (should never happen)
                        return
                    
                    # spent = contractsToUSDT( canDoContracts, contractSize, price, leverage )
                    # returned = contractsToUSDT( positionContracts, contractSize, price, leverage )
                    # #available = available - spent + returned
                    # available -= spent * 1.02
                    # available += returned * 0.97
                    # #so, how many countracs can we do with this
                    # canDoContracts = contractsFromUSDT( available, contractSize, precision, price, leverage )

                    # if( canDoContracts < 1 ):
                    #     printf( timeNow(), " * WARNING * Insuficient balance for the second order. Skipping." )
                    #     return
                    
                    # if( quantity > canDoContracts ):
                    #     printf( timeNow(), " * WARNING * Insuficient balance. Reducing by", quantity - canDoContracts, "contracts" )
                    #     quantity = canDoContracts

                    account.ordersQueue.append( order_c( symbol, type, quantity, leverage, 1.0 ) )
                    return
            # fall through



        if( canDoContracts < account.findMinimumAmountForSymbol(symbol) ):
            printf( timeNow(), " * ERROR * Insuficient balance:", available )
            return

        # if( quantity > canDoContracts ):
        #     printf( timeNow(), " * WARNING * Insuficient balance. Reducing to", canDoContracts)
        #     quantity = canDoContracts
        
        account.ordersQueue.append( order_c( symbol, type, quantity, leverage ) )
        return

    printf( timeNow(), " * WARNING: Something went wrong. No order was placed")



def Alert( data ):

    isJSON = is_json(data)

    account = None

    #make a first pass looking for account id
    if( isJSON ):
        jdata = json.loads(data)
        for key, value in jdata.items():
            if key == 'id':
                for a in accounts:
                    if( value == a.id ):
                        account = a
                        break
        if( account == None ):
            if verbose : print( timeNow(), ' * ERROR * Account ID not found.' )
            return
        parseAlert( data, isJSON, account )
        return

    # if plain text accept several alerts separated by line breaks

    #first lets find out if there's more than one commands inside the alert message
    lines = data.split("\n")
    for line in lines:
        account = None
        tokens = line.split()
        for token in tokens:
            for a in accounts:
                if( token == a.accountName ):
                    account = a
                    break
        if( account == None ):
            if verbose : print( timeNow(), ' * ERROR * Account ID not found.' )
            # TMP HACK!
            account = accounts[0]

        parseAlert( line, isJSON, account )




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
        printf( " * ERROR PARSING ACCOUNT INFORMATION: EXCHANGE" )
        continue

    account_id = ac.get('ACCOUNT_ID')
    if( account_id == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: ACCOUNT_ID" )
        continue

    api_key = ac.get('API_KEY')
    if( api_key == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: API_KEY" )
        continue

    secret_key = ac.get('SECRET_KEY')
    if( secret_key == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: SECRET_KEY" )
        continue

    password = ac.get('PASSWORD')
    if( password == None ):
        password = ""
        continue

    print( timeNow(), " * Initializing account: [", account_id, "] in [", exchange , ']')
    accounts.append( account_c( exchange, account_id, api_key, secret_key, password ) )


if( len(accounts) == 0 ):
    printf( " * FATAL ERROR: No valid accounts found. Please edit 'accounts.json' and introduce your API keys" )
    raise SystemExit()

############################################

#define the webhook server
app = Flask(__name__)
#silencing flask useless spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.disabled = True

@app.route('/whook', methods=['GET','POST'])
def webhook():
    if request.method == 'POST':
        data = request.get_data(as_text=True)
        printf( '\n' + str(timeNow()), "ALERT:", data.replace('\n', '') )
        printf('----------------------------')
        Alert(data)
        return 'success', 200
    if request.method == 'GET':
        wmsg = open( 'webhook.log', encoding="utf-8" )
        text = wmsg.read()
        return app.response_class(text, mimetype='text/plain; charset=utf-8')
    else:
        abort(400)

# start the positions fetching loop
timerFetchPositions = RepeatTimer(20, refreshPositions)
timerFetchPositions.start()

timerOrdersQueue = RepeatTimer(0.5, updateOrdersQueue)
timerOrdersQueue.start()

#start the webhook server
if __name__ == '__main__':
    printf( " * Listening" )
    app.run(host="0.0.0.0", port=80, debug=False)


#timerFetchPositions.cancel()
#timerOrdersQueue.cancel()

