#!/usr/bin/env python3
import sys
from gamedeck.app import GameDeck

if __name__ == "__main__":
    sys.exit(GameDeck().run(sys.argv[1:]))

