Hi! Hope you're doing well, and thanks again for all the support with our market making setup.

Could I ask for your advice on something small we noticed? When the market gets busy, some of our orders take a bit longer to reach the book, around 10–50 ms between orderTime and ts in the level3 feed, while at quiet times it's 1–2 ms. Most of the time it's no problem at all, and we fully understand everyone slows down a little at peak moments.

We checked our side carefully first: our software and network take about 1–2 ms, and it doesn't seem related to how often we send or cancel. So we were wondering whether it could have to do with how our account is set up, for example the Unified Account, the endpoint we use, or post-only orders.

Is there a setup you would recommend for market makers to get the best order entry at busy times? We're happy to change anything on our side or run a small test if that helps.

In case it's useful, a few example orders (UTC, 2026-10-02, XBTUSDCM):
495605399030927361 (20:58:57)
495605371856031745 (20:58:50)
495590420819021827 (19:59:25)

No rush at all, and thanks a lot!
