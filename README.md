# whook

WHOOK is a web hook for handling Tradingview Alerts to crypto exchanges in perpetual USDT futures.

Whook prioritizes realiability over speed. If you're looking for high frequency trading Whook is not for you.
Whook will do everything it can to fullfill orders, including resending rejected orders until they time out (currently 40 seconds), reducing the quantity of the order when the balance is not enough and dividing the order in two at reversing positions when there's not enough balance for doing it at once.

Whook only makes market orders. Limit orders, take profit and stop loss are not supported.<br>
Whook only uses one-side mode. Hedge mode is not supported.<br>
It's also always using isolated marging. However you should be able to change this relatively easy if you want to.


##### Disclaimer: This project is for my personal use. I'm not taking feature requests.

Currently supported exchanges:
- Kucoin futures
- Bitget futures
- Coinex futures
- Phemex futures ( also Phemex testnet: https://testnet.phemex.com )
- Bybit futures ( also Bybit testnet: https://testnet.bybit.com )
  
Broken support:
- Bingx: There is some problem with the conversion from USDT to contracts. Sending orders in contracts should work fine.
- Mexc: The exchange's API has been in mantainance since 2022. It denies placing any order.


### ALERT SYNTAX ###

#### As plain text:

* Symbol format:: ETHUSDT, ETH/USDT, ETH/USDT:USDT

* Account id: Just add the id. No command associated. Account id must include at least one non-numeric character and obviously it shouldn't be the same as any of the command names.

* Commands:<br>
buy or long - places buy order.<br>
sell or short - places sell order.<br>
position or pos - goes to a position of the given value. Use a positive value for Long and a negative value for Short.<br>
close - closes the position (position 0 also does it).<br>

* Quantities:<br>
[value]$ - quantity in USDT. No command associated. Just the number and the dollar sign.<br>
[value]@ - quantity in contracts. No command associated. Just the number and the 'at' sign.<br>
[value] - quantity in base currency. Just the number without any extra character. Base currency is the coin you're trading.<br>
[value]x or x[value] - defines the leverage.<br>

Examples:<br>
- Buy command using USDT:<br>
[account_id] [symbol] [command] [value in USDT] [leverage] - **myKucoinA ETH/USDT buy 300$ x3**<br>

- Position command using contracts:<br>
[symbol] [command] [value in contracts] [leverage] [account_id] - **ETH/USDT position -500@ x3 myKucoinA**<br>
Notice: This is a short position. For a long position use a positive value. Same goes when the value is in USDT<br>
The value of a contract differs from exchange to exchange. You have to check it in the exchange under contract information<br>
Example of a position alert from a strategy in Tradingview: myKucoinA {{ticker}} pos {{strategy.position_size}} x3

- Sell command using base currency:<br>
[account_id] [symbol] [command] [value in USDT] [leverage] - **myKucoinA ETH/USDT sell 0.25 x3**<br>
This would sell 0.25ETH<br>

- Close position<br>
[account_id] [symbol] [command] - **myKucoinA ETH/USD close**<br>

Several orders can be included in the same alert, separated by line breaks. For example, you can send the orders for 2 different accounts inside the same alert.


### API KEYS ###
When you first launch the script it will generate a json file. This file is a template to fill the accounts API data. This file can contain as many accounts as you want separated by commas. It looks like this:


[<br>
&emsp;	{<br>
&emsp;&emsp;		"EXCHANGE":"kucoinfutures", <br>
&emsp;&emsp;		"ACCOUNT_ID":"your_account_name", <br>
&emsp;&emsp;		"API_KEY":"your_api_key", <br>
&emsp;&emsp;		"SECRET_KEY":"your_secret_key", <br>
&emsp;&emsp;		"PASSWORD":"your_API_password"<br>
&emsp;	}<br>
]<br>


You have to fill your API key and SECRET key information in the accounts.json file.<br>
The ACCOUNT_ID field is the name you give to the account. It's to be included in the alert message to identify the account.<br>
The password field is required by Kucoin and Bitget but other exchanges may or may not use it. If your exchange doesn't give you a password when creating the API key just leave the field blank.<br>
The EXCHANGE field is self explanatory. Valid exchange names are:<br> 
- "**kucoinfutures**"<br>
- "**bitget**"<br>
- "**coinex**"<br>
- "**phemex**"<br>
- "**phemexdemo**" (for testnet)<br>
- "**bybit**"<br>
- "**bybitdemo**"(for testnet)<br>
- "**bingx**" (not fully functional)<br>
- "**mexc**" (exchange has API orders disabled due to manteinance)<br>


### HOW TO INSTALL AND RUN ###

"If you want to go for a quick effortless test I recommend to copy/paste the script into a free account at 'https://replit.com'. It installs all modules for you so you don't have to do anything. Do **not** use it to host the real server. It goes idle as soon as you close the browser, and your API keys could be discovered."

##### Windows:

- Download and install python. During the installation make sure to *enable the system PATH option* and at the end of the installation *allow it to unlimit windows PATH length*: https://www.python.org/downloads/
- Open the windows cmd prompt (type cmd in the windows search at the taskbar). Install the required modules by typing "pip install ccxt" and "pip install flask" in the cmd prompt

With these you can already run the script, but it won't have access online. For giving it access to the internet you should use:

- ngrok. Create a free ngrok account. Download the last version of ngrok and unzip it. Copy the auth code the website gives you. Launch the software and paste the auth code into the console (with the authcode ngrok will be able to stay open forever). Then type in the ngrok console: "ngrok http 80". This will create an internet address that you can copy. You have to add /whook at the end of it to access the whook server.<br>

Example of an address: https://e579-139-47-50-49.ngrok-free.app/whook<br>

- You can launch the script by double clicking main.py (as long as you enabled the PATH options at installing python) or by creating a .bat file in the same directory as main.py like this:<br>

@echo off<br>
python.exe main.py<br>
pause<br>

If you have troubles with the cmd prompt or the bat file you can also install Visual Code in the server and run it from there.


### HOW TO HOST IN AWS ### 
(the easy way)

You can host a server in AWS EC2 for free. It can be a linux server or a windows server. You can find many tutorials in Youtube on how to do it. Here's a (slightly outdated) tutorial for windows: https://youtu.be/9z5YOXhxD9Q.<br>
I host it in a Windows_server 2022 edition which was the latest at the time of writing this readme.<br>

Once you have your virtual machine running follow the steps in the section above ("How to intall and run").

I'm not a linux user so I struggled to open the ports in the Linux virtual machine. If you have experience in Linux this may be easy to you.


### KNOWN BUGS ### 
- BingX contracSize and precision seem to be either wrong or work in a different scale than the rest of exchanges. The USDT to contracts conversion is returning wrong values. BingX support is uncomplete and I don't think I'll complete it. But I won't remove it either since most of it is implemented.
- Mexc API has been in maintainance mode since 2022, and, while it connects and sets up fine, orders are denied. I think Mexc would be functional if the orders went throught, but I don't know if they will ever enable them again.
- Things will most likely go south if you have a position with a leverage and you order the same position with a different leverage. Some exchanges may take the leverage change as you trying to change the leverage of the current position but not changing the amount of contracts. I'll try to handle it but it's not a big priority for me.


