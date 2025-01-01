from enigma_machine import EnigmaMachine
import asyncio

enigma = EnigmaMachine()
enigma.add_tasks(enigma.ble.tasks)
enigma.add_tasks(enigma.wifi.tasks)
enigma.add_tasks(enigma.display.tasks)

# Run all tasks
try:
    asyncio.run(enigma.run_tasks())
except KeyboardInterrupt:
    print("Interrupted by user")






