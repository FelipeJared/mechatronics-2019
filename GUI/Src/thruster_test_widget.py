'''
Copyright 2019, David Pierce Walker-Howell, All rights reserved
Author: David Pierce Walker-Howell<piercedhowell@gmail.com>
Last Modified 3/06/2019
Description: This PyQt widget is for testing thruster by simply
                turning individual ones on and off.
'''
import sys
import os

PARAM_PATH = os.path.join("..", "..", "Sub", "Src", "Params")
sys.path.append(PARAM_PATH)
MECHOS_CONFIG_FILE_PATH = os.path.join(PARAM_PATH, "mechos_network_configs.txt")
from mechos_network_configs import MechOS_Network_Configs

MESSAGE_TYPE_PATH = os.path.join("..", "..", "Message_Types")
sys.path.append(MESSAGE_TYPE_PATH)
from thruster_message import Thruster_Message

from MechOS import mechos
from PyQt5.QtWidgets import QWidget, QApplication, QGridLayout, QCheckBox, QLabel, QSlider
from PyQt5.QtWidgets import QLineEdit, QVBoxLayout
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QTimer
import time

class Thruster_Test(QWidget):
    '''
    This class is a PyQt widget for performing thruster individual thruster
    test.
    '''
    def __init__(self):
        '''
        Initialize the layout for the widget by setting its color and instantiating
        its components.

        Parameters:
            N/A

        Returns:
            N/A
        '''

        QWidget.__init__(self)

        #Set background color of the widget
        #nav_gui_palette = self.palette()
        #nav_gui_palette.setColor(self.backgroundRole(), QColor(64, 64, 64))
        #self.setPalette(nav_gui_palette)

        #Create widgets main layout structer
        self.linking_layout = QGridLayout(self)
        self.setLayout(self.linking_layout)

        #Set up sub widgets for check boxes and sliders
        self._thruster_check_boxes()
        self._thruster_slider()


        configs = MechOS_Network_Configs(MECHOS_CONFIG_FILE_PATH)._get_network_parameters()
        #MechOS publisher to send thrust test messages to thruster controller
        self.thruster_test_node = mechos.Node("THRUSTER_TEST_GUI", '192.168.1.2', '192.168.1.14')
        self.publisher = self.thruster_test_node.create_publisher("THRUSTS", Thruster_Message(), protocol="tcp")

        self.thrusts = [0, 0, 0, 0, 0, 0, 0, 0]

    def _thruster_check_boxes(self):
        '''
        Generate the check boxes to choose which thrusters to turn on.

        Parameter:
            N/A

        Returns:
            N/a
        '''

        #Make checkboxes for thrusters
        self.thruster_check_boxes = []
        self.thruster_check_boxes_layout = QGridLayout()

        #make a check box for each of 8 thrusters.
        for thruster_id in range(8):
            title = "Thruster " + str(thruster_id + 1) + ":"
            self.thruster_check_boxes.append(QCheckBox(title))
            self.thruster_check_boxes[thruster_id].setStyleSheet("color: black")

            #create signal/slot to update which thrusters are active
            self.thruster_check_boxes[thruster_id].stateChanged.connect(self._update_test_thrust)

            #Place thrusters 1 - 4 on left side of layout
            if(thruster_id <= 3):
                self.thruster_check_boxes_layout.addWidget(self.thruster_check_boxes[thruster_id],
                                    thruster_id, 0)
            #Place thrusters 3-8 on right side of layout
            else:
                self.thruster_check_boxes_layout.addWidget(self.thruster_check_boxes[thruster_id],
                                    thruster_id - 4, 1)

        #Add check box layout to the whole Thruster Test widget
        self.linking_layout.addLayout(self.thruster_check_boxes_layout, 0, 0)

    def _thruster_slider(self):
        '''
        Generate the slider to choose the thrust amount of the thrusters to
        test.

        Parameters:
            N/A
        Returns:
            N/A
        '''
        #make a layout to place all the components of the slider layout
        self.thruster_slider_layout = QGridLayout()

        self.thrust_slider = QSlider(Qt.Horizontal)
        self.thrust_slider.setMaximum(100)
        self.thrust_slider.setMinimum(-100)
        self.thrust_slider.setValue(0) #Set the initial value of the slider to 0
        self.thrust_slider.setTickPosition(QSlider.TicksBelow)
        self.thrust_slider.setTickInterval(10)

        #create signal/slot to change thrust to activated thrusters
        self.thrust_slider.valueChanged.connect(self._update_test_thrust)

        self.thrust_slider_display = QLineEdit()
        self.thrust_slider_display.setText(str(0) + "%")

        slider_label = QLabel("Thrust %")
        slider_label.setStyleSheet("color: black")
        self.thruster_slider_layout.addWidget(slider_label, 0, 0)
        self.thruster_slider_layout.addWidget(self.thrust_slider, 0, 1)
        self.thruster_slider_layout.addWidget(self.thrust_slider_display, 1, 1)

        #Add thrust slider to Thruster Test widget layout
        self.linking_layout.addLayout(self.thruster_slider_layout, 0, 1)

    def _update_test_thrust(self):
        '''
        Call back function to update thrust values if check boxes are pressed
        and/or the thrust value (percentage) changes. This function is called when
        signals are received by the slider or check boxes.

        Parameters:
            N/A

        Returns:
            N/A
        '''
        desired_thrust = self.thrust_slider.value()
        self.thrust_slider_display.setText(str(desired_thrust) + "%")

        #Set each of the proto fields with the desired thrust if checkbox is checked
        if self.thruster_check_boxes[0].isChecked():
            self.thrusts[0] = desired_thrust
        else:
            self.thrusts[0] = 0
        if self.thruster_check_boxes[1].isChecked():
            self.thrusts[1]  = desired_thrust
        else:
            self.thrusts[1] = 0
        if self.thruster_check_boxes[2].isChecked():
            self.thrusts[2]  = desired_thrust
        else:
            self.thrusts[2] = 0
        if self.thruster_check_boxes[3].isChecked():
            self.thrusts[3]  = desired_thrust
        else:
            self.thrusts[3] = 0
        if self.thruster_check_boxes[4].isChecked():
            self.thrusts[4]  = desired_thrust
        else:
            self.thrusts[4] = 0
        if self.thruster_check_boxes[5].isChecked():
            self.thrusts[5]  = desired_thrust
        else:
            self.thrusts[5] = 0
        if self.thruster_check_boxes[6].isChecked():
            self.thrusts[6] = desired_thrust
        else:
            self.thrusts[6] = 0
        if self.thruster_check_boxes[7].isChecked():
            self.thrusts[7] = desired_thrust
        else:
            self.thrusts[7] = 0



        #publish data to mechos network
        self.publisher.publish(self.thrusts)


if __name__ == "__main__":
    import sys
    app = QApplication([])
    thrust_test_gui = Thruster_Test()
    thrust_test_gui.show()
    sys.exit(app.exec_())
