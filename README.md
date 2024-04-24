# whook

WHOOK is a web hook for handling Tradingview Alerts to crypto exchanges in perpetual USDT futures.

Whook prioritizes reliability over speed. If you're looking for high frequency trading Whook is not for you.
Whook will do everything it can to fullfill orders, including resending rejected orders until they time out (currently 40 seconds), reducing the quantity of the order when the balance is not enough and dividing the order in two at reversing positions when there's not enough balance for doing it at once.

Whook only makes market orders and limit orders. Take profit and stop loss are not supported.<br>
Whook only uses one-side mode. Hedge mode is not supported.<br>

You don't need to be a programmer nor know how to clone a repository to use Whook. All you need is to download the **main.py** file and follow the instructions below.

##### Disclaimer: This project is for my personal use. I'm not taking feature requests.

Currently supported exchanges:
- **Kucoin** futures
- **Bitget** futures
- **Coinex** futures
- **Bingx**
- **OKX** futures ( also its demo mode )
- **Bybit** futures ( also [Bybit testnet](https://testnet.bybit.com) )
- **Binance** futures ( also [Binance futures testnet](https://testnet.binancefuture.com) )
- **Phemex** futures ( also [Phemex testnet](https://testnet.phemex.com) )
- **Kraken** futures ( also [Kraken futures testnet](https://demo-futures.kraken.com) )


### ALERT SYNTAX ###

* Symbol format:: ETHUSDT, ETHUSDT.P, ETH/USDT, ETH/USDT:USDT. All these formats will be accepted.

* Account id: Just add the id you create for the account. No command associated. Account id must include at least one non-numeric character and obviously it shouldn't be the same as any of the command names.

* Commands:<br>
**buy** - places buy order.<br>
**sell** - places sell order.<br>
**position or pos** - goes to a position of the given value. Use a positive value for Long and a negative value for Short.<br>
**close** - closes the position (position 0 also does it).<br>
**limit:[customID]:[price]** - Combined with buy/sell commads creates a limit order. The three fields must be separated by a colon with no spaces.<br>
Every limit order must have assigned its own unique ID so it can be identified for cancelling it<br>
**cancel:[customID]** - Cancels a limit order by its customID. The symbol is required in the order.<br>
**cancel:all** - Special keyword which cancels all orders from that symbol at once.<br>

* Quantities:<br>
**[value]** - quantity in base currency. Just the number without any extra character. Base currency is the coin you're trading.<br>
**[value]$** - quantity in USDT. No command associated. Just the number and the dollar sign.<br>
**[value]@** - quantity in contracts. No command associated. Just the number and the 'at' sign.<br>
**[value]%** - quantity as percentage of total USDT balance. Use a negative value for shorts when using the position command.<br>
All quantity types are interchangeable. All can be used with buy/sell/position commands.

* Leverage:<br>
**[value]x or x[value]** - The x identifies this value as the leverage.<br>

Examples:<br>
- **Buy command using USDT:**<br>
[account_id] [symbol] [command] [value in USDT] [leverage] - **myKucoinA ETH/USDT buy 300$ x3**<br>

- **Position command using contracts:**<br>
[symbol] [command] [value in contracts] [leverage] [account_id] - **ETH/USDT position -500@ x3 myKucoinA**<br>
Notice: This is a short position. For a long position use a positive value. Same goes when the value is in USDT<br>
The value of a contract differs from exchange to exchange. You have to check it in the exchange under contract information<br>
Example of a position alert from a strategy in Tradingview:<br>
**myKucoinA {{ticker}} pos {{strategy.position_size}} x3**<br>
This alert is all you should really need for running 90% of the strategies in TV

- **Sell command using base currency:**<br>
[account_id] [symbol] [command] [value in USDT] [leverage] - **myKucoinA ETH/USDT sell 0.25 x3**<br>
This would sell 0.25ETH<br>

- **Close position**<br>
[account_id] [symbol] [command] [percentage] - **myKucoinA ETH/USD close 33.33%**<br>
The percentage parameter is optional. If not included it will close the full position.

- **Limit buy command using USDT:**<br>
[account_id] [symbol] [command] [value in USDT] [leverage] [limit:[customID]:[price]] - **myKucoinA ETH/USDT buy 300$ x3 limit:myid002:1012**<br>
Will open a buy order at 1012. The management of the customID falls on you if you ever want to cancel it. Remember you can't open 2 orders with the same customID<br>
Some exchange peculiarities to be aware of:<br>
Bybit will not accept the same customID twice, even if the previous order is already cancelled.<br>
Coinex only accepts numeric customIDs.<br>

- **Cancel limit order:**<br>
[account_id] [symbol] [cancel:[customID]] - **myKucoinA ETH/USDT cancel:myid002**<br>
[account_id] [symbol] [cancel:all] - **myKucoinA ETH/USDT cancel:all** all orders from this symbol<br>


Several orders can be included in the same alert, separated by line breaks. For example, you can send the orders for 2 different accounts inside the same alert. (the console will be a little messy when doing this, but the logs will be clean)<br>

It's possible to add comments inside the alert message. The comment must be in a new line and begin with a double slash '//'. Why? You ask. Because I often forget the setting I used when I created the alert! Whook will simply ignore that line when parsing the alert.


### HOW TO INSTALL AND RUN ###

##### Windows:

- Download and install [python](https://www.python.org/downloads/). During the installation make sure to *enable the system PATH option* and at the end of the installation *allow it to unlimit windows PATH length* <br>
- Open the windows cmd prompt (type cmd in the windows search at the taskbar). Install the required python modules by typing "pip install ccxt" and "pip install flask" in the cmd prompt.<br>

With these you can already run the script, but it won't have access online. For giving it access to the internet I recommend to use:<br>

- [ngrok](https://ngrok.com/download). Create a free ngrok account. Download the last version of ngrok and unzip it. In the ngrok website they provide an auth key, copy it. Launch the software and paste the auth code into the ngrok console (with the authcode ngrok will be able to stay open forever). Then type in the ngrok console: "ngrok http 80". This will create an internet address for your webhook. You have to add /whook at the end of it to comunicate with the Whook server. This will be the address you introduce in the tradingview alert<br>

Note: Ngrok now allows free accounts to create one static domain. It allows to close Ngrok and keep the same address the next time you open it, which is nice.

Example of an address: https://e579-139-47-50-49.ngrok-free.app/whook<br>

- You can launch the script by double clicking main.py (as long as you enabled the PATH options at installing python). If for some reason Windows failed to associate .py files with python.exe you can create a .bat file inside the same directory as main.py with this inside<br>
@echo off<br>
python.exe main.py<br>
pause<br>


### CONFIGURATION - API KEYS ###
When you first launch the script it will create an accounts.json file in the script directory and exit with a 'no accounts found' error. This file is a template to configure the accounts API data. This file can contain **as many accounts as you want separated by commas**. It looks like this:


[<br>
&emsp;	{<br>
&emsp;&emsp;		"ACCOUNT_ID":"your_account_name", <br>
&emsp;&emsp;		"EXCHANGE":"exchange_name", <br>
&emsp;&emsp;		"API_KEY":"your_api_key", <br>
&emsp;&emsp;		"SECRET_KEY":"your_secret_key", <br>
&emsp;&emsp;		"PASSWORD":"your_API_password",<br>
&emsp;&emsp;		"MARGIN_MODE":"isolated"<br>
&emsp;	}<br>
]<br>


You have to fill your **API_KEY** and **SECRET_KEY** information in the accounts.json file.<br>
The **ACCOUNT_ID** field is the **name you give to the account**. It's to be included in the alert message to identify the alert target account.<br>
The **PASSWORD** field is required by Kucoin and Bitget but other exchanges may or may not use it. If your exchange doesn't give you a password when creating the API key just leave the field blank.<br>
The **MARGIN_MODE** field defines the margin mode in which the account will operate. Valid names "isolated" or "cross". Defaults to isolated. It's only allowed to define it in a per account basis. There's no support to define it per symbol.<br>
The **EXCHANGE** field is self explanatory. Valid exchange names are:<br> 
- "**kucoinfutures**"<br>
- "**bitget**"<br>
- "**coinex**"<br>
- "**bingx**<br>
- "**okx**"<br>
- "**okxdemo**"(for testnet)<br>
- "**bybit**"<br>
- "**bybitdemo**"(for testnet)<br>
- "**binance**"<br>
- "**binancedemo**"(for testnet)<br>
- "**krakenfutures**"<br>
- "**krakendemo**"(for testnet)<br>
- "**phemex**"<br>
- "**phemexdemo**" (for testnet)<br>

There is also one optional key: **'SETTLE_COIN'** for cases where you want to trade non-USDT pairs (or non-USD in the case of Kraken). Different settle coins can't be combined, tho. Whook will only use one at once per account. If you want to trade in several settle coins you can create an account for each settle coin (they can reuse the same API keys).


### HOW TO HOST IN AWS ### 
(the easy way)

You can host a server in AWS EC2 for free. It can be a linux server or a windows server. You can find many tutorials in Youtube on how to do it. Here's a (slightly outdated) tutorial for windows: https://youtu.be/9z5YOXhxD9Q.<br>
I host it in a Windows_server 2022 edition which was the latest at the time of writing this readme.<br>

Once you have your virtual machine running follow the steps in the section above ("How to intall and run").

I'm not a linux user so I struggled to open the ports in the Linux virtual machine. If you have experience in Linux this may be easy to you.


### KNOWN BUGS ### 
- Kraken: Whook is unable to set the margin mode. It will use whatever is set in the exchange for that symbol.
- Kraken can't check leverage boundaries. If a order exceeds the maximum leverage the console may spam until the order times out.
- BingX: Limit orders aren't setting the custom ID. They can only be cancelled using cancel:all
- Things will most likely go south if you have a position with a leverage and you order the same position with a different leverage. Some exchanges may take the leverage change as you trying to change the leverage of the current position but not changing the amount of contracts. The order will go through, but the resulting position will depend on the exchange. I'll try to handle it but it's not a big priority for me.

### TO DO LIST ### 
- Split whook in 2 files, one containing the accounts class. So it can be imported by other scripts to create orders directly. In short, for bots.
- Add some account configuration optional keys. Like order timeout, alert timeout, margin mode...
- 'pricelock' a made up mode to attempt to place market orders as limit orders.
- Create some form of past trades storage better than the logs. Usable for trading performance analytics.
