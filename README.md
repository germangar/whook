# whook

WHOOK is a web hook for handling Tradingview Alerts to Kucoin. Other exchanges may be added in the future.

Whook prioritizes realiability over speed. If you're looking for high frequency trading, this is not for you.
It will do everything it can to fullfill orders, including reducing the quantity or the order when the balance is not enough.

Disclaimer: This project is for my personal use. I'm not taking feature requests.

#######################################
########## Alert syntax ###############
#######################################

As plain text:

* Symbol format:: ETHUSDT, ETHUSDTM, ETH/USDT, ETH/USDT:USDT

* Account id: Just add the id. No command associated. Account id must include at least one character.

* Commands:
buy or long - places buy order
sell or short - places sell order
position or pos - goes to a position of the given value (no matter what the current position is)
close - closes the position (position 0 also does it)

* Quantities:
<value> - quantity in contracts. No command associated, just the number
<value>$ - quantity in USDT. No command associated, just the number and the dollar sign
<value>x or x<value> - defines the leverage.

Examples:
kucoin000 ETH/USDT buy 300$ x3
ETH/USDT pos 300 x3 kucoin000
kucoin000 ETH/USD close

As JSON message:

JSON Messages are barely supported (I don't use them). Only accepts one alert per message and direct USDT orders aren't implemented.
Orders must come in contracts.

{
"symbol": "BTC/USDT",
"command": "buy",
"quantity": "12",
"leverage": "3",
"id" : "kucoin000"
}

synonims: symbol, ticker // command, cmd, action


################################################
#####  HOW TO SET UP ###########################
################################################

If you have experience with python: It requires to pip install ccxt and flask.

If you don't know anything about python and you are on Windows I recommend to do this:
- Install the latest version of Python from their website. During the install make sure to *enable the system PATH option* and at the end of the installation *allow it to unlimit windows PATH length*
https://www.python.org/downloads/

- Install Visual Code and in the extensions tab install the python extension. *Restart visual code*. In the terminal pip install ccxt and flask (just type pip install ccxt and pip install flask. Make sure you restarted VC after enabling the python extension. And make sure python was already installed)
https://code.visualstudio.com/download

With these you can already run the script, but it won't have access online. For giving it access to the internet you should use:

- ngrok. Create a free ngrok account. Download the last version of ngrok and unzip it. Launch the software and copy paste the auth code they give you on the website (with the authcode ngrok will be able to stay open forever). 
Then type in the ngrok console: "ngrok http 80". This will create an internet address that you can copy from the console. You have to add /whook to it to access the hook server.

Example of an address: https://e579-139-47-50-49.ngrok-free.app/whook

This address will continue stable until you close ngrok. Launching ngrok again will produce a new address.


##### API KEYS #######
When you first launch the script it will generate a json file. This file is a template to fill the accounts API data. This file can contain more than one account.
You have to fill your API key information in the accounts.json file. The password field is required for Kucoin but other exchanges may or may not use it.
The code allows to configure a Binance spot account, but it is not supported yet. It will bug out if you try to use it.


#############################################
########## HOW TO HOST IN AWS ###############
#############################################

You can host a server in AWS EC2 for free. It can be a linux server or a windows server. You can find many tutorials in Youtube on how to do it.

I'm not a linux user so I struggled to open the ports in Linux. If you have experience in Linux this may be easy to you.

Here's a (slightly outdated) tutorial for windows: https://youtu.be/9z5YOXhxD9Q

I simply hosted it in a Windows_server 2022 edition. Basic steps are pretty much the same as for the local install:
- Download and install python following the same steps.
- pip install ccxt and flask from the windows cmd terminal (if you have troubles with this see the last line of this readme)
- Download and execute ngrok the same way
- You can launch the script by creating a .bat file in the same directory as main.py like this:
@echo off
python.exe main.py
pause

If you have troubles with the bat file you can also install Visual Code in the server and run it from there.
