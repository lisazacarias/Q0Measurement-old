################################################################################
# Utility classes to hold calibration data for a cryomodule, and Q0 measurement
# data for each of that cryomodule's cavities
# Authors: Lisa Zacarias, Ben Ripman
################################################################################


class Cryomodule:
    # We're assuming that the convention is going to be to run the calibration
    # on cavity 1, but we're leaving some wiggle room in case
    def __init__(self, cryModNumSLAC, cryModNumJLAB, calFileName,
                 refValvePos, refHeaterVal, calCavNum=1):

        self.cryModNumSLAC = cryModNumSLAC
        self.cryModNumJLAB = cryModNumJLAB
        self.dataFileName = calFileName
        self.refValvePos = refValvePos
        self.refHeaterVal = refHeaterVal
        self.calCavNum = calCavNum

        jlabNumStr = str(self.cryModNumJLAB)
        self.valvePV = "CPV:CM0" + jlabNumStr + ":3001:JT:POS_RBV"
        self.dsLevelPV = "CLL:CM0" + jlabNumStr + ":2301:DS:LVL"
        self.usLevelPV = "CLL:CM0" + jlabNumStr + ":2601:US:LVL"

        # These buffers store calibration data read from the CSV dataFileName
        self.unixTimeBuffer = []
        self.timeBuffer = []
        self.valvePosBuffer = []
        self.heatLoadBuffer = []
        self.downstreamLevelBuffer = []
        self.upstreamLevelBuffer = []

        # Maps this cryomodule's PV's to its corresponding data buffers
        self.pvBufferMap = {self.valvePV: self.valvePosBuffer,
                            self.dsLevelPV: self.downstreamLevelBuffer,
                            self.usLevelPV: self.upstreamLevelBuffer}

        # Give each cryomodule 8 cavities
        self.cavities = {i: self.Cavity(parent=self, cavNumber=i)
                         for i in range(1, 9)}

    # Returns a list of the PVs used for its data acquisition, including
    # the PV of the cavity heater used for calibration
    def getPVs(self):
        return [self.valvePV, self.dsLevelPV, self.usLevelPV,
                self.cavities[self.calCavNum].heaterPV]

    class Cavity:
        def __init__(self, parent, cavNumber):
            self.parent = parent

            self.cavityNumber = cavNumber
            self.dataFileName = None

            self.refGradientVal = None

            heaterPVStr = "CHTR:CM0{cryModNum}:1{cavNum}55:HV:POWER"
            self.heaterPV = heaterPVStr.format(cryModNum=parent.cryModNumJLAB,
                                               cavNum=cavNumber)

            gradientPVStr = "ACCL:L1B:0{cryModNum}{cavNum}0:GACT"
            self.gradientPV = gradientPVStr.format(cryModNum=parent.cryModNumJLAB,
                                                   cavNum=cavNumber)

            # These buffers store Q0 measurement data read from the CSV
            # dataFileName
            self.unixTimeBuffer = []
            self.timeBuffer = []
            self.valvePosBuffer = []
            self.heatLoadBuffer = []
            self.downstreamLevelBuffer = []
            self.upstreamLevelBuffer = []
            self.gradientBuffer = []

            # Maps this cavity's PVs to its corresponding data buffers
            # (including a couple of PVs from its parent cryomodule)
            self.pvBufferMap = {self.parent.valvePV: self.valvePosBuffer,
                                self.parent.dsLevelPV:
                                    self.downstreamLevelBuffer,
                                self.parent.usLevelPV: self.upstreamLevelBuffer,
                                self.heaterPV: self.heatLoadBuffer,
                                self.gradientPV: self.gradientBuffer}

        # Similar to the Cryomodule function, it just has the gradient PV
        # instead of the heater one
        def getPVs(self):
            return [self.parent.valvePV, self.parent.dsLevelPV,
                    self.parent.usLevelPV, self.gradientPV, self.heaterPV]

        # The @property annotation is effectively a shortcut for defining a
        # class variable and giving it a custom getter function (so now
        # whenever someone calls Cavity.refValvePos, it'll return the parent
        # value)
        @property
        def refValvePos(self):
            return self.parent.refValvePos

        @property
        def refHeaterVal(self):
            return self.parent.refHeaterVal

        @property
        def cryModNumSLAC(self):
            return self.parent.cryModNumSLAC

        @property
        def cryModNumJLAB(self):
            return self.parent.cryModNumJLAB


def main():
    cryomodule = Cryomodule(cryModNumSLAC=12, cryModNumJLAB=2, calFileName="",
                            refValvePos=0, refHeaterVal=0)
    for idx, cav in cryomodule.cavities.iteritems():
        print cav.gradientPV
        print cav.heaterPV


if __name__ == '__main__':
    main()
