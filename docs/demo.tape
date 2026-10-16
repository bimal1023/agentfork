Output docs/demo.gif
Set FontSize 15
Set Width 1300
Set Height 800
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

Hide
Type "source .venv/bin/activate && clear"
Enter
Show

Type "# The agent refunded $4,999 for a $49.99 laptop. What happened?"
Enter
Sleep 1s
Type "agentfork show 5a75d971"
Enter
Sleep 4s

Type "# Test a fix: feed step 2 the right data, replay step 1 from cache"
Enter
Type `agentfork fork 5a75d971 --step 2 --output '{"order_id": "A123", "item": "laptop", "amount_usd": 49.99, "status": "delivered"}'`
Enter
Sleep 7s

Type "agentfork diff 5a75d971 ebb96ab1"
Enter
Sleep 6s
