import numpy as np
import matplotlib.pyplot as plt

pos1 = 80 #initial position
pos2 = 70. #final position
deltaP = pos1 - pos2
tmax = 10.+abs(deltaP)/4.
t = np.linspace(0,tmax,20)

trajectory = deltaP * np.cos(np.pi*t/tmax) / 2. - (deltaP / 2. - pos1)
plt.plot(t,trajectory)
plt.ylabel("Position (um)")
plt.xlabel("Time (ms)")
plt.show()

