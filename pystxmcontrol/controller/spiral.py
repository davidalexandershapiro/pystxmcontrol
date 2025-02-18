
import numpy as np
import math

def parameterize_spiral(spiraltype,outonly,GUIchange):   #don't worry about sampling issues if using constant sampling.  

	if outOnly == 1:

		wavelengthfactor = 1
	else:
		wavelengthfactor = 2
	
	LmaxXYGUIinputs=["maxFreqXY", "TRSR", "inRatio", "spiralNumLoops", "sampleDensity"]# should this be mutable?
	if spiraltype=='InstrumentLimits' & GUIchange in LmaxXYGUIinputs:
		if outOnly==1:
			numloops_in = (2*round(numloops*inRatio/(1-inRatio)+0.5)-1)/2	#//n+0.5 loops in to enforce continous phase because passing through the center is half a loop. can be as small as 0.5 loops.
		

		if Outonly==1:
			TfastestoutXYlimit = numLoops/(maxFreqXY*(1-inRatio)) #//time for fastest outspiral given XYfrequency limit
			TfastestinXYlimit = numLoops_in/(maxFreqXY*inRatio) #//time for fastest inspiral given XYfrequency limit
			TfastestXYlimit = max(TfastestoutXYlimit , TfastestinXYlimit ) #//use only max because spiraltime is just one frame
		else:
			TfastestXYlimit = numLoops/maxFreqXY #// time for fastest spiral given XYfrequency limit
		totaltime = max(totaltime, T_min_xy)#  //increase total time because of requested new number of loops and XY limit. 
######Need to write a method to record the newly calculated time of scan. 
		if totaltime == T_min_xy:
			print("Reaching frequency limit of xy-scanner. Adjusted time per scan.")
#			break
	
	LtimeGUIinputs=["TRSR","sampleDensity","spiralTime", "frameRate"]  #probably not goign to use TRSR
	if spiraltype=='InstrumentLimits' & GUIchange in LtimeGUIinputs:  	
		if outOnly==1:
			NumLoopout = floor(totaltime*(1-inRatio)*maxFreqXY)	#// calculates number of loops in outSpiral
			NumLoopin = floor(totalTime*inRatio*maxFreqXY*(1-inRatio)/inRatio)-2	#// inSpiral (-2 accounts for rounding in numloops_in)
			Numlooplimit = min(NumLoopout , NumLoopin)
		else:
			Numlooplimit =  floor(totaltime*maxFreqXY)
		if Numlooplimit < 5: # //Use a minimum number of loops of 5 which matches the value in the user variables wave low limit.
			Numlooplimit = 5
			unfeasible = 1  #
			print("Reaching speed limit of xy-scanner. Change speed or scan size.")

				
		numLoops =  min(numLoops, Numlooplimit)
	######Need to write a method to record the newly calculated number of loops.
		if numLoops == Numlooplimit:
			print(" Reaching frequency limit of xy-scanner. Adjusted number of loops.")
#			break
	
#		//////////////////////////////////////////
#		// sets desired sampling rate and corrects scan time given discrete sampling rates and number of points in the array being a multiple of base_wavesize
#		//////////////////////////////////////////
#		 // considers only TRSR_max and Density_min at the outside of the scan area
		if outOnly==1:
			outscantime= totaltime*(1-inRatio)
		else:
			outscantime= totaltime
			
		inverseA =  outscantime*maxFreqXY/numLoops #    //this variable is 1/a where a is the variable from the paper which represents how long the scan would take if CAV at XY frequency limit. 
		Timetransition = 1 - sqrt(1 - 1/inverseA ** 2)   #  //this is the time at the transition to CLV as a fraction of total time, t*L
		VeltransitionNorm = 2 * Timetransition *inverseA ** 2   #  //this is the normalized velocity of the scan after transition to CLV. actual speed is pi*numloops*scansize*YY/totaltime
		if inverseA < 1:
			print("Spiral not feasible!")
	
		
 		

	#end parameterize_spiral



def spiralcreator(samplingfrequency , scantime , numloops, clockwise, spiralscantype, inratio, scanradius, maxFreqXY ): 
	
#	outonly = 1  #I am assuming outonly for all waveforms.  It is better.
	numpnts = scantime * samplingfrequency
	numpntsin = round ( inratio * numpnts )
	numpntsout = numpnts - numpntsin
	Spiralindex = np.arange(0, numpnts)
	Spiralinindex = np.arange(0, numpntsin)
	Spiraloutindex = np.arange(0, numpntsout)

	if clockwise==1:  #Could just use clockwise and have it be turned negative by the GUI instead of using a boolean.
		clockwisecoef = -1
	else:
		clockwisecoef = 1

	

	if spiralscantype == "CAV":
		numloopsin = max([0,2*math.ceil((numloops*inratio)-1)/2])+0.5 
		totalnumloops = numloops + numloopsin ## numloops in scan out then scan in with additional 180 degree phase at end//round(numloops/(1-inratio))##//CAV just needs a linear angular function.
		numpntsin = round(numpnts*(numloopsin/totalnumloops))
		numpntsout = numpnts-numpntsin
		Spiralindex = np.arange(0, numpnts)
		Spiralinindex = np.arange(0, numpntsin)
		Spiraloutindex = np.arange(0, numpntsout)
		spiraltheta = clockwisecoef*2*math.pi*totalnumloops*Spiralindex/numpnts
		spiralRout = scanradius*Spiraloutindex/numpntsout
		spiralRin = scanradius*(numpntsin-Spiralinindex)/numpntsin
		spiralR = np.append(spiralRout, spiralRin)
		
	if spiralscantype == "CLV":
		##disregard donut scans for now
		#numloopsin = max([0,2*math.ceil((numloops*inratio)-1)/2])+0.5 #typical number of loops in based on inratio
		numloopsin = max([0, 2*math.ceil((numloops*inratio/2)-1)/2])+0.5 #use half the number of loops in so that it is lower speed than scan out.
		numpntsin = round(numpnts*inratio)
		numpntsout = numpnts-numpntsin
		Spiralinindex = np.arange(0, numpntsin)
		Spiraloutindex = np.arange(0, numpntsout)
		spiralouttheta = clockwisecoef*2*math.pi*numloops*np.sqrt(Spiraloutindex/numpntsout)
		spiraloutR = scanradius*np.sqrt(Spiraloutindex/numpntsout)
		
		#The following lines are CLV in
		spiralintheta = clockwisecoef*(2*math.pi*numloops+2*math.pi*numloopsin-2*math.pi*numloopsin*np.sqrt((numpntsin-Spiralinindex)/numpntsin))
		spiralinR = scanradius*np.sqrt((numpntsin-Spiralinindex)/numpntsin)
		#the following lines are CAV in
		#spiralintheta = clockwisecoef*2*math.pi*(numloops+numloopsin*Spiralinindex/numpntsin)
		#spiralinR = scanradius*(numpntsin-Spiralinindex)/numpntsin 
		
		spiraltheta = np.append(spiralouttheta, spiralintheta)
		spiralR = np.append(spiraloutR, spiralinR)
	
	if spiralscantype == "InstrumentLimits":

		numloopsin = max([0,2*math.ceil((numloops*inratio)-1)/2])+0.5 #typical number of loops in based on inratio
		#numloopsin = max([0, 2*math.ceil((numloops*inratio/2)-1)/2])+0.5 #use half the number of loops in so that it is lower speed than scan out.
		numpntsin = round(numpnts*inratio)
		numpntsout = numpnts-numpntsin

		scantimeout = scantime * ( 1 - inratio )
		inverseA = scantimeout * maxFreqXY / numloops #    //this variable is 1/a where a is the variable from the paper which represents how long the scan would take if CAV at XY frequency limit. also called AA in previous code.
		if inverseA <= 1:
		    print("Cannot complete the scan in the indicated time, while considering the instruments limits.... ")
		#    break
		Timetransition = 1 - np.sqrt(1 - 1/inverseA ** 2)   #  //this is the time at the transition to CLV as a fraction of total time, t*L also called ZZ in previous code
		VeltransitionNorm = 2 * Timetransition * inverseA ** 2   #  //this is the normalized velocity of the scan after transition to CLV. actual speed is pi*numloops*scansize*YY/totaltime
		SpiralInstCAVoutindex = np.arange(0, np.floor(Timetransition * numpntsout ) )
		SpiralInstCLVoutindex = np.arange(np.floor(Timetransition * numpntsout ), numpntsout )
		spiralInstCAVoutR = scanradius * inverseA * (SpiralInstCAVoutindex /numpntsout) 
		spiralInstCLVoutR = scanradius * np.sqrt(2* inverseA**2 * Timetransition * SpiralInstCLVoutindex /numpntsout  + 1 - VeltransitionNorm)
		spiraloutR = np.append( spiralInstCAVoutR , spiralInstCLVoutR )
		spiralInstCAVouttheta =  clockwisecoef*2*math.pi*numloops* inverseA * (SpiralInstCAVoutindex /numpntsout) 
		spiralInstCLVouttheta =  clockwisecoef*2*math.pi*numloops* np.sqrt(2* inverseA**2 * Timetransition * SpiralInstCLVoutindex /numpntsout  + 1 - VeltransitionNorm)
		spiralouttheta = np.append( spiralInstCAVouttheta , spiralInstCLVouttheta )

		scantimein = scantime -scantimeout
		inverseAin = scantimein * maxFreqXY / numloopsin #    //this variable is 1/a where a is the variable from the paper which represents how long the scan would take if CAV at XY frequency limit. also called AA in previous code.
		Timetransitionin = 1 - np.sqrt(1 - 1/inverseAin ** 2)   #  //this is the time at the transition to CLV as a fraction of total time, t*L also called ZZ in previous code
		VeltransitionNormin = 2 * Timetransitionin * inverseAin ** 2   #  //this is the normalized velocity of the scan after transition to CLV. actual speed is pi*numloops*scansize*YY/totaltime
		SpiralInstCLVinindex = np.arange( numpntsin, np.floor(Timetransitionin * numpntsin ) ,-1 )
		SpiralInstCAVinindex = np.arange( np.floor(Timetransitionin * numpntsin ),0,-1 )
		spiralInstCLVinR = scanradius * np.sqrt(2* inverseAin ** 2 * Timetransitionin * SpiralInstCLVinindex /numpntsin  + 1 - VeltransitionNormin)
		spiralInstCAVinR = scanradius * inverseAin *  SpiralInstCAVinindex /numpntsin 
		spiralinR = np.append(spiralInstCLVinR, spiralInstCAVinR  )
		spiralInstCAVintheta =  -1* (clockwisecoef*2*math.pi*numloopsin* inverseAin * (SpiralInstCAVinindex /numpntsin) ) + 2*math.pi*numloops + clockwisecoef*2*math.pi*numloopsin 
		spiralInstCLVintheta =  -1* (clockwisecoef*2*math.pi*numloopsin* np.sqrt(2* inverseAin**2 * Timetransitionin * SpiralInstCLVinindex /numpntsin  + 1 - VeltransitionNormin)) + 2*math.pi*numloops + clockwisecoef*2*math.pi*numloopsin
		spiralintheta = np.append( spiralInstCLVintheta, spiralInstCAVintheta  )
		spiraltheta = np.append( spiralouttheta, spiralintheta)
		spiralR = np.append(spiraloutR, spiralinR)
		

	spiralx=spiralR*np.cos(spiraltheta)
	spiraly=spiralR*np.sin(spiraltheta)
	spiralout = (spiralx, spiraly)
	return spiralout
	#end spiralcreator	



#//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
#//moveToPointWaveBuilder
#//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
#function/wave moveToPointWaveBuilder(newX, newY)
#	variable newX, newY
#	variable/g base_wavesize
#//	print "StartedMoveToPointWaveBuilder"
#	variable currentX = td_readvalue("ARC.Output.X")
#	variable currentY = td_readvalue("ARC.Output.Y")
#	
#	variable distance = sqrt((newX - currentX)^2 + (newY - currentY)^2)  //Distance in Volts
#	variable/g velocity = abs(GV("avgVelocity")/GV("XPiezoSens")) //Velocity in highVoltage Volts/Second
#	if(velocity<20)
#		velocity=20
#	endif
#//	variable velocity = //GV("avgVelocity") /GV("XPiezoSens") //Velocity in highVoltage Volts/Second
#//	print "velocity during move is", velocity, " V/s"
#	variable/g movetime = 10*distance/velocity  //10 is safetyfactor
#	print "movetime during move to xy  is", movetime, " s"
#	make/o/n=(base_wavesize) moveT = p * movetime / base_wavesize
#	make/o/n=(base_wavesize, 2) moveToPointOut
#	
#	if (movetime==0)
#		movetime = 1	// no move needed, prevent division by 0
#	endif
#	
#	moveToPointOut[0,base_wavesize-1][0] = (movetime - moveT[p]) / movetime * currentX + moveT[p] / movetime * newX
#	moveToPointOut[0,base_wavesize-1][1] = (movetime - moveT[p]) / movetime * currentY + moveT[p] / movetime * newY
#	return moveToPointOut
#end //moveToPointWaveBuilder

#//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
#//moveToPointXY
#//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
#function movetoxy(ctrlname, stringcallback)
#	string ctrlname
#	string stringcallback
#//	Print "Started MovetoXY"
#//	td_WriteString("Event.1","Clear")
#//	clearBanks()//maybe this causes the jump when we load the waves.
#	//Construct a line between actual position and start position of spiral or measure tilt
#	wave spiralxout, spiralyout, tiltxout, tiltyout
#	if(cmpstr("MeasureTiltCoefficients", ctrlName) == 0)
#		wave moveToPointOut = moveToPointWaveBuilder(tiltXOut[0], tiltYOut[0])
#	else
#		wave moveToPointOut = moveToPointWaveBuilder(SpiralXOut[0], SpiralYOut[0])
#	endif
#	variable/g movetime, controllerFreq
#	variable/g base_wavesize
#	variable movetointerpol = ceil(movetime* controllerFreq / base_wavesize+.000001)
#	variable error
#	make/o/n=(base_wavesize) MoveZ, DummyWave, moveXOut, moveYOut
#	moveXOut = moveToPointOut[p][0]
#	moveYOut = moveToPointOut[p][1]
#	setscale/I x, 0, movetime,  movexout, moveyout
#	error = td_xSetOutWavePair(0, "1", "ARC.Output.X", moveXOut, "ARC.Output.Y", moveYOut, movetointerpol)
#	error_message("Error encountered moving tip to starting position. Error code", error)
#	error = td_xSetInWavePair(0,"1","Height", MoveZ, "Amplitude", DummyWave, stringcallback, movetointerpol) //Record Height during the movetopointout to have a trigger for a callback goes to SpiralCallback or measuretiltcallback 
#	error_message("Error encountered recording while moving tip to starting position. Error code", error)
#	td_WriteString("Event.1","once")
#	PV("ScanNotActive",1)
#	userInputOnOff(0)

#end //movetoXY


