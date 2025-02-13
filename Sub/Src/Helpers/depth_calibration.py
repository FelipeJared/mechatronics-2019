
'''
Author: Mohammad Shafi
Last modified: 04/04/2019
Description: This is a helper script to calibrate depth properly. It sets the bias
to the depth the sub reads at 0, and calculates depth accordingly. It then publishes
this data to the paramter server.
References: sensor_driver.py, Backplane_Sensor_Data.py by David Pierce Walker Howell
'''

import sys
import os

BACKPLANE_PATH = os.path.join("..", "SensorHub")
sys.path.append(BACKPLANE_PATH)

PARAM_PATH = os.path.join("..", "Params")
sys.path.append(PARAM_PATH)
MECHOS_CONFIG_FILE_PATH = os.path.join(PARAM_PATH, "mechos_network_configs.txt")
from mechos_network_configs import MechOS_Network_Configs


import numpy as np
import math
import threading
import serial
import time
from Backplane_Sensor_Data import Backplane_Handler
from MechOS import mechos

class Depth_Calibrator:
    '''
    Initializes depth calibrator object. Use this to create connection to backplane, establish
    Mechatronics parameter server connection, and ensure that we are receiving backplane data
    '''
    def __init__(self):

        #Get the mechos network parameters
        configs = MechOS_Network_Configs(MECHOS_CONFIG_FILE_PATH)._get_network_parameters()

        self.param_serv = mechos.Parameter_Server_Client(configs["param_ip"], configs["param_port"])
        self.param_serv.use_parameter_database(configs["param_server_path"])

        backplane_com_port = self.param_serv.get_param("COM_Ports/backplane")
        self.backplane_driver_thread = Backplane_Handler(backplane_com_port)
        self.threading_lock = threading.Lock()
        self.run_thread = True
        self.backplane_driver_thread.start()
        time.sleep(1.5) #Makes sure Backplane is up and running

def calculate_depth_scale(input, offset):
    '''
    This function calculates our depth scale. The equation we use is as follows:
    user input = (raw pressure data - bias)/depth scale. The user input is the depth we want the sub to
    submerge to, while the bias is a running average of our raw pressure data we are receiving
    at 0.
    '''
    depth_scale = np.array([(offset[0] / input), (offset[1] / input)])
    return depth_scale

def calculate_pressure(pressure_x, pressure_y, depth_calibrator):
    '''
    This function will attempt to accurately calculate depth pressure at any given point. The parameters are
    our two pressure variables and the depth calibrator object. Repeatedly receive pressure data and take an average
    to get as close as we can to the true reading at that depth
    '''
    pressure_x = 0
    pressure_y = 0
    while(depth_calibrator.backplane_driver_thread.raw_depth_data[0] == 0):
        print("No depth data")
    for x in range(0, 100):
        pressure_x = pressure_x + depth_calibrator.backplane_driver_thread.raw_depth_data[0]
        pressure_y = pressure_y + depth_calibrator.backplane_driver_thread.raw_depth_data[1]

        time.sleep(0.05)
    print(pressure_x)
    pressure = np.array([(pressure_x/100), (pressure_y/100)])
    return pressure

def check_response(question):
    '''
    Return true if user's keyboard input is a y. If the user wants to proceed, we proceed. If not, ask the question again
    '''
    if question == 'y' or question == 'Y':
        return True
    else:
        question = input("Sorry, invalid response. Please enter 'y'")
        return check_response(question)

if __name__ == '__main__':
    '''
    A lot going on in main. First, a Depth Calibrator object is created, to initialize connections and
    have a paramater server clinet running connected to MechOS. The variables in the 2-D depth array are
    initailized. User always asked if they want to begin calculating offset. After offset is calculated,
    user is then prompted to enter a depth, and asked if they want to begin. Once a yes is received, depth depth
    scale is calculated and updated on the parameter server.
    '''
    depth_calibrator = Depth_Calibrator()

    prompt = input("Are you ready to calculate offset?")

    if(check_response(prompt)):
        raw_pressure_data_x = 0
        raw_pressure_data_y = 0
        average = calculate_pressure(raw_pressure_data_x, raw_pressure_data_y, depth_calibrator)
        offset = np.array([(average[0]), average[1]])
        print("Offset", offset)
        depth_calibrator.param_serv.set_param("Sensors/trans_1_bias", str(offset[0]))
        depth_calibrator.param_serv.set_param("Sensors/trans_2_bias", str(offset[1]))

    curr_depth = float(input("Enter the depth you want the sub to calculate scale at: "))
    ask = input("Begin calculating depth_scale?")

    if(check_response(ask)):
        offset = np.array([(float(depth_calibrator.param_serv.get_param("Sensors/trans_1_bias"))), (float(depth_calibrator.param_serv.get_param("Sensors/trans_2_bias")))])
        new_pressure_x = 0
        new_pressure_y = 0
        new_pressure = calculate_pressure(new_pressure_x, new_pressure_y, depth_calibrator)
        difference = np.array([abs(new_pressure[0] - offset[0]), abs(new_pressure[1] - offset[1])])
        depth_scale = calculate_depth_scale(curr_depth, difference)
        print("Scale", depth_scale)

        #If the thruser depth scale is calculated to be zero, then that transducer may not be plugged in.
        #Set the parameter in the parameter to 1 in order to make sure there is no divisions by zero.
        if(depth_scale[0] == 0):
            depth_scale[0] = 1
            print("**Possible Error with Depth Scale for Transducer 1**. Depth Scale Param being overriden to 1.")
        depth_calibrator.param_serv.set_param("Sensors/trans_1_scaling", str(depth_scale[0]))

        if(depth_scale[1] == 0):
            depth_scale[1] = 1
            print("**Possible Error with Depth Scale for Transducer 2**. Depth Scale Param being overriden to 1.")
        depth_calibrator.param_serv.set_param("Sensors/trans_2_scaling", str(depth_scale[1]))

    time.sleep(0.1)
