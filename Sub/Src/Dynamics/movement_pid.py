'''
Copyright 2019, David Pierce Walker-Howell, All rights reserved

Author: David Pierce Walker-Howell<piercedhowell@gmail.com>
Last Modified: 08/05/2019
Description: This module contains a PID based movement controller that is used
            to control the six degrees of freedom control of Perseverance.
'''
import sys
import os

import numpy as np
HELPER_PATH = os.path.join("..", "Helpers")
sys.path.append(HELPER_PATH)
import util_timer

PARAM_PATH = os.path.join("..", "Params")
sys.path.append(PARAM_PATH)
MECHOS_CONFIG_FILE_PATH = os.path.join(PARAM_PATH, "mechos_network_configs.txt")
from mechos_network_configs import MechOS_Network_Configs

from thruster import Thruster
from pid_controller import PID_Controller
from MechOS import mechos
import serial
import math

class Movement_PID:
    '''
    A movement controller for Perseverance that relies on PID controller to control
    the 6 degrees of freedom.
    '''

    def __init__(self):
        '''
        Initialize the thrusters and PID controllers on Perseverance.

        Parameters:
            N/A

        Returns:
            N/A
        '''
        #Get the mechos network parameters
        configs = MechOS_Network_Configs(MECHOS_CONFIG_FILE_PATH)._get_network_parameters()

        #Initialize parameter server client to get and set parameters related to
        #the PID controller. This includes update time and PID contstants for
        #each degree of freedom.
        self.param_serv = mechos.Parameter_Server_Client(configs["param_ip"], configs["param_port"])
        self.param_serv.use_parameter_database(configs["param_server_path"])

        #Initialize serial connection to the maestro
        com_port = self.param_serv.get_param("COM_Ports/maestro")
        maestro_serial_obj = serial.Serial(com_port, 9600)

        #Initialize all 8 thrusters (max thrust 80%)
        max_thrust = float(self.param_serv.get_param("Control/max_thrust"))

        self.thrusters = [None, None, None, None, None, None, None, None]
        self.thrusters[0] = Thruster(maestro_serial_obj, 1, [0, 0, 1], [1, -1, 0], max_thrust, True)
        self.thrusters[1] = Thruster(maestro_serial_obj, 2, [0, 1, 0], [1, 0, 0], max_thrust, True)
        self.thrusters[2] = Thruster(maestro_serial_obj, 3, [0, 0, 1], [1, 1, 0], max_thrust, False)
        self.thrusters[3] = Thruster(maestro_serial_obj, 4, [1, 0, 0], [0, 1, 0], max_thrust, False)
        self.thrusters[4] = Thruster(maestro_serial_obj, 5, [0, 0, 1], [-1, 1, 0], max_thrust, True)
        self.thrusters[5] = Thruster(maestro_serial_obj, 6, [0, 1, 0], [-1, 0, 0], max_thrust, True)
        self.thrusters[6] = Thruster(maestro_serial_obj, 7, [0, 0, 1], [-1, -1, 0], max_thrust, False)
        self.thrusters[7] = Thruster(maestro_serial_obj, 8, [1, 0, 0], [0, -1, 0], max_thrust, True)

        #Used to notify when to hold depth based on the remote control trigger for depth.
        self.remote_desired_depth = 0
        self.remote_depth_recorded = False
        self.remote_yaw_min_thrust = float(self.param_serv.get_param("Control/Remote/yaw_min"))
        self.remote_yaw_max_thrust = float(self.param_serv.get_param("Control/Remote/yaw_max"))
        self.remote_x_min_thrust = float(self.param_serv.get_param("Control/Remote/x_min"))
        self.remote_x_max_thrust = float(self.param_serv.get_param("Control/Remote/x_max"))
        self.remote_y_min_thrust = float(self.param_serv.get_param("Control/Remote/y_min"))
        self.remote_y_max_thrust = float(self.param_serv.get_param("Control/Remote/y_max"))

        #Initialize the PID controllers for control system
        self.set_up_PID_controllers(True)

    def set_up_PID_controllers(self, initialization=False):
        '''
        Setup the PID controllers with the initial values set in the subs
        parameter xml server file. Also update the strength parameter for
        each thrusters.

        Parameters:
            initialization: If it is the first time that this function is being called,
                            set initialization to true so it creates the pid controllers.
                            If false, it just updates the controller values.

        Returns:
            N/A
        '''
        d_t = float(self.param_serv.get_param("Control/PID/dt"))
        roll_p = float(self.param_serv.get_param("Control/PID/roll_pid/p"))
        roll_i = float(self.param_serv.get_param("Control/PID/roll_pid/i"))
        roll_d = float(self.param_serv.get_param("Control/PID/roll_pid/d"))
        self.roll_min_error = float(self.param_serv.get_param("Control/PID/roll_pid/min_error"))
        self.roll_max_error = float(self.param_serv.get_param("Control/PID/roll_pid/max_error"))
        self.max_roll = float(self.param_serv.get_param("Control/Limits/max_roll"))

        pitch_p = float(self.param_serv.get_param("Control/PID/pitch_pid/p"))
        pitch_i = float(self.param_serv.get_param("Control/PID/pitch_pid/i"))
        pitch_d = float(self.param_serv.get_param("Control/PID/pitch_pid/d"))
        self.pitch_min_error = float(self.param_serv.get_param("Control/PID/pitch_pid/min_error"))
        self.pitch_max_error = float(self.param_serv.get_param("Control/PID/pitch_pid/max_error"))
        self.max_pitch = float(self.param_serv.get_param("Control/Limits/max_pitch"))

        yaw_p = float(self.param_serv.get_param("Control/PID/yaw_pid/p"))
        yaw_i = float(self.param_serv.get_param("Control/PID/yaw_pid/i"))
        yaw_d = float(self.param_serv.get_param("Control/PID/yaw_pid/d"))
        self.yaw_min_error = float(self.param_serv.get_param("Control/PID/yaw_pid/min_error"))
        self.yaw_max_error = float(self.param_serv.get_param("Control/PID/yaw_pid/max_error"))


        x_p = float(self.param_serv.get_param("Control/PID/x_pid/p"))
        x_i = float(self.param_serv.get_param("Control/PID/x_pid/i"))
        x_d = float(self.param_serv.get_param("Control/PID/x_pid/d"))
        self.x_min_error = float(self.param_serv.get_param("Control/PID/x_pid/min_error"))
        self.x_max_error = float(self.param_serv.get_param("Control/PID/x_pid/max_error"))

        y_p = float(self.param_serv.get_param("Control/PID/y_pid/p"))
        y_i = float(self.param_serv.get_param("Control/PID/y_pid/i"))
        y_d = float(self.param_serv.get_param("Control/PID/y_pid/d"))
        self.y_min_error = float(self.param_serv.get_param("Control/PID/y_pid/min_error"))
        self.y_max_error = float(self.param_serv.get_param("Control/PID/y_pid/max_error"))

        #z = depth pid
        z_p = float(self.param_serv.get_param("Control/PID/z_pid/p"))
        z_i = float(self.param_serv.get_param("Control/PID/z_pid/i"))
        z_d = float(self.param_serv.get_param("Control/PID/z_pid/d"))
        self.z_min_error = float(self.param_serv.get_param("Control/PID/z_pid/min_error"))
        self.z_max_error = float(self.param_serv.get_param("Control/PID/z_pid/max_error"))
        self.min_z = float(self.param_serv.get_param("Control/Limits/min_z"))
        self.max_z = float(self.param_serv.get_param("Control/Limits/max_z"))

        #The bias term is a thruster vale to set to thruster 1, 3, 5, 7 to make the sub neutrally bouyant.
        #This term is added to the proportional gain controller.
        #(K_p * error) + bias
        #Essentially this parameter will make the sub act neutrally bouyant below the activate bias depth.
        self.z_bias = float(self.param_serv.get_param("Control/PID/z_pid/bias"))
        self.z_active_bias_depth = float(self.param_serv.get_param("Control/PID/z_pid/active_bias_depth"))

        #If running the script with initialization true, create PID_Controller objects
        if(initialization):
            print("[INFO]: Initializing PID Controllers.")
            self.roll_pid_controller = PID_Controller(roll_p, roll_i, roll_d, d_t)
            self.pitch_pid_controller = PID_Controller(pitch_p, pitch_i, pitch_d, d_t)
            self.yaw_pid_controller = PID_Controller(yaw_p, yaw_i, yaw_d, d_t)
            self.x_pid_controller = PID_Controller(x_p, x_i, x_d, d_t)
            self.y_pid_controller = PID_Controller(y_p, y_i, y_d, d_t)
            self.z_pid_controller = PID_Controller(z_p, z_i, z_d, d_t)

        else:
            print("[INFO]: Updating PID Controller Configurations.")
            self.roll_pid_controller.set_gains(roll_p, roll_i, roll_d, d_t)
            self.pitch_pid_controller.set_gains(pitch_p, pitch_i, pitch_d, d_t)
            self.yaw_pid_controller.set_gains(yaw_p, yaw_i, yaw_d, d_t)
            self.x_pid_controller.set_gains(x_p, x_i, x_d, d_t)
            self.y_pid_controller.set_gains(y_p, y_i, y_d, d_t)
            self.z_pid_controller.set_gains(z_p, z_i, z_d, d_t)

        #TODO: Physically balance the sub so that this can be deprecated.
        #Thruster Strengths (these are used to give more strengths to weeker thrusters in the case that the sub is imbalanced)
        #Each index corresponds to the thruster id.
        self.thruster_strengths = [0, 0, 0, 0, 0, 0, 0, 0]

        for i in range(8):
            param_path = "Control/Thruster_Strengths/T%d" % (i+1)
            self.thruster_strengths[i] = float(self.param_serv.get_param(param_path))

        #Get the depth at which the thruster strength offsets will be used (in ft)
        self.thruster_offset_active_depth = float(self.param_serv.get_param("Control/Thruster_Strengths/active_depth"))



    def simple_thrust(self, thrusts):
        '''
        Individually sets each thruster PWM given the PWMs in the thrusts
        list.

        Parameters:
            thrusts: A list of length 8 containing a thrust value (%) between
            [-100, 100]. The list should be in order of the thruster ids.

        Returns:
            N/A
        '''

        for thruster_id, thrust in enumerate(thrusts):
            self.thrusters[thruster_id].set_thrust(thrust)

    def controlled_thrust(self, roll_control, pitch_control, yaw_control, x_control,
                        y_control, z_control, curr_z_pos):
        '''
        Function takes control outputs from calculated by the PID values and applys
        them to the 6 degree control matrix to determine the thrust for each thruster
        to reach desired point.

        Parameters:
            roll_control: The control output from the roll pid controller.
            pitch_control: The control output from the pitch pid controller.
            yaw_control: The control output from the yaw pid controller.
            x_control: The control output from the x translation pid controller.
            y_control: The control output from the y translation pid controller.
            z_control: The control output from the z translation pid controller.
            curr_z_pos: The current depth position of the sub. This is needed to know
                        when to activate thruster offsets to help hold the sub level.
        Returns:
            N/A
        '''
        for thruster_id, thruster in enumerate(self.thrusters):
            #Multiplied roll control and x_control by negative one to account for the thrusters going in the
            #wrong direction.
            #Also only thruster 2 and 6 are used for yaw, achieve better results this way.
            #To add in thrusters 4 and 8 for yaw, add the following comment line to the addition.
            #       (yaw_control * thruster.orientation[0] * thruster.location[1])

            thrust = (-1 * roll_control * thruster.orientation[2] * thruster.location[1]) + \
                     (pitch_control * thruster.orientation[2] * thruster.location[0]) + \
                     (yaw_control * thruster.orientation[1] * thruster.location[0]) + \
                     (-1 * x_control * thruster.orientation[0]) + \
                     (y_control * thruster.orientation[1]) + \
                     (z_control * thruster.orientation[2])

            #Write the thrust to the given thruster. Some thrusters have an additional offset to given them
            #a higher strength. This is used to help balance out weigth distribution issues with the sub.
            #if(curr_z_pos >= self.thruster_offset_active_depth):
            #    thrust = thrust + self.thruster_strengths[thruster_id]

            #Since the center of mass of the sub is not in the center of the axises of the sub,
            #some thruster will need to produce more torque to have movement about that axis,
            #be stable.
            thrust = thrust + (thrust * self.thruster_strengths[thruster_id])

            if(curr_z_pos >= self.z_active_bias_depth):

                thrust = thrust + (self.z_bias * thruster.orientation[2]) #Make sure only thrusters controlling z have this parameter

            self.thrusters[thruster_id].set_thrust(thrust)


    def bound_error(self, unbounded_error, min_error, max_error):
        '''
        This function will check if the unbounded error is within the range
        of the max and min error. If it is not, it will force it to be.

        Parameter:
            unbounded_error: The error that has not yet been checked if it
                            is within the error limits
            min_error: The minimum value that you want your error to be.
            max_error: The maximum value that you want your error to be.
        Returns:
            N/A
        '''
        if(unbounded_error < min_error):
            unbounded_error = min_error
            return(unbounded_error)
        elif(unbounded_error > max_error):
            unbounded_error = max_error
            return(unbounded_error)
        else:
            return(unbounded_error)

    def advance_move(self, current_position, desired_position):
        '''
        Given the current position and desired positions of the AUV, obtain the pid
        control outputs for all 6 degrees of freedom.

        Parameters:
            current_position: A list of the most up-to-date current position.
                            List format: [roll, pitch, yaw, x_pos, y_pos, depth]
            desired_position: A list containing the desired positions of each
                                axis. Same list format as the current_position
                                parameter.

        Returns:
            error: A list of of the errors that where evaluted for each axis.
                    List Format: [roll_error, pitch_error, yaw_error, x_pos_error, y_pos_error, depth_error]
        '''

        #calculate the error of each degree of freedom
        error = [0, 0, 0, 0, 0, 0]

        #Make sure roll is within maximum limit
        if(abs(desired_position[0]) > self.max_roll):
            desired_position[0] = math.copysign(self.max_roll, desired_position[0])
            print("[WARNING]: Absolute of desired roll %0.2f is greater than the max limit %0.2f" % (desired_position[0], self.max_roll))

        error[0] = self.bound_error(desired_position[0] - current_position[0], self.roll_min_error, self.roll_max_error) #roll error

        #Make sure pitch is within maximum limit
        if(abs(desired_position[1]) > self.max_pitch):
            desired_position[1] = math.copysign(self.max_pitch, desired_position[1])
            print("[WARNING]: Absolute of desired pitch %0.2f is greater than the max limit %0.2f" % (desired_position[0], self.max_pitch))

        error[1] = self.bound_error(desired_position[1] - current_position[1], self.pitch_min_error, self.pitch_max_error) #pitch error

        #Calculate yaw error. The logic includes calculating error for choosing shortest angle to travel
        desired_yaw = desired_position[2]
        curr_yaw = current_position[2]

        yaw_error = desired_yaw - curr_yaw
        if(abs(yaw_error) > 180):

            if(yaw_error < 0):
                yaw_error = yaw_error + 360
            else:
                yaw_error = yaw_error - 360

        error[2] = self.bound_error(yaw_error, self.yaw_min_error, self.yaw_max_error)
        #Calculate the error in the x and y position (relative to the sub) given the current north/east position.
        #Using rotation matrix.
        #North and East error
        north_error = desired_position[3] - current_position[3]
        east_error = desired_position[4] - current_position[4]
        yaw_rad = math.radians(curr_yaw) #convert yaw from degrees to radians

        x_error = (math.cos(yaw_rad) * north_error) + (math.sin(yaw_rad) * east_error)
        y_error = (-1 * math.sin(yaw_rad) * north_error) + (math.cos(yaw_rad) * east_error)
        error[3] = self.bound_error(x_error, self.x_min_error, self.x_max_error)
        error[4] = self.bound_error(y_error, self.y_min_error, self.y_max_error)

        if(desired_position[5] < self.min_z):
            print("[WARNING]: Desired depth %0.2f is less than the min limit %0.2f" % (desired_position[5], self.min_z))
            desired_position[5] = self.min_z

        elif(desired_position[5] > self.max_z):
            print("[WARNING]: Desired depth %0.2f is greater than the max limit %0.2f" % (desired_position[5], self.max_z))
            desired_position[5] = self.max_z

        error[5] = self.bound_error(desired_position[5] - current_position[5], self.z_min_error, self.z_max_error) #z_pos (depth)

        #Get the thrusts from the PID controllers to move towards desired pos.
        roll_control = self.roll_pid_controller.control_step(error[0])
        pitch_control = self.pitch_pid_controller.control_step(error[1])
        yaw_control = self.yaw_pid_controller.control_step(error[2])
        x_control = self.x_pid_controller.control_step(error[3])
        y_control = self.y_pid_controller.control_step(error[4])
        z_control = self.z_pid_controller.control_step(error[5])
        #Write the controls to thrusters
        self.controlled_thrust(roll_control, pitch_control, yaw_control, x_control, y_control, z_control, current_position[5])
        return error

    def remote_move(self, current_position, remote_commands):
        '''
        Accepts spoofed error input for each degree of freedom from the xbox controller
        to utilize the pid controllers for remote control movement.

        Parameters:
            current_position: A list of the most up-to-date current position.
                            List format: [roll, pitch, yaw, x_pos, y_pos, depth]
            remote_commands: A list of the spoofed errors for [yaw, x_pos, y_pos, depth] to
                    utilize the remote control to perform movement with the PID
                    controller.

        Returns:
            N/A
        '''
        #always want roll and pitch to be level at 0 degrees
        roll_error = self.bound_error(0.0 - current_position[0], self.roll_min_error, self.roll_max_error) #roll error
        pitch_error = self.bound_error(0.0 - current_position[1], self.pitch_min_error, self.pitch_max_error) #pitch error


        #Interpolate errors to the min and max errors set in the parameter server

        yaw_control = np.interp(remote_commands[0], [-1, 1], [self.remote_yaw_min_thrust, self.remote_yaw_max_thrust])
        x_control = np.interp(remote_commands[1], [-1, 1], [self.remote_x_min_thrust, self.remote_x_max_thrust])
        y_control = np.interp(remote_commands[2], [-1, 1], [self.remote_y_min_thrust, self.remote_y_max_thrust])

        #When the trigger is released for controlling depth, record the depth and hold.
        if(remote_commands[4]):

            if(self.remote_depth_recorded == False):
                self.remote_desired_depth = current_position[5]
                self.remote_depth_recorded = True

            depth_error = self.bound_error(self.remote_desired_depth - current_position[5], \
                              self.z_min_error, self.z_max_error) #z_pos (depth)

        else:
            self.remote_depth_recorded = False
            self.remote_desired_depth = 0

            #Since the min and max error is not the same in terms of absolute value,
            #interpolation needs to be handled seperate for up and down movements.
            if(remote_commands[3] <= 0.0):

                depth_error = np.interp(remote_commands[3], [-1, 0], [self.z_min_error, 0])
            else:
                depth_error = np.interp(remote_commands[3], [0, 1], [0, self.z_max_error])


        #Get the thrusts from the PID controllers to move towards desired pos.
        roll_control = self.roll_pid_controller.control_step(roll_error)
        pitch_control = self.pitch_pid_controller.control_step(pitch_error)
        z_control = self.z_pid_controller.control_step(depth_error)
        self.controlled_thrust(roll_control, pitch_control, yaw_control,-1 * x_control, y_control, z_control, current_position[5])

        return

    #This is a helper function to be used initially for tuning the roll, pitch
    #and depth PID values. Once tuned, please use advance_move instead.
    def simple_depth_move_no_yaw(self, curr_roll, curr_pitch,curr_z_pos,
                          desired_roll, desired_pitch, desired_z_pos):
        '''
        Without carrying about x axis position, y axis position, or yaw, use the PID controllers
        to go down to a give depth (desired_z_pos) with a give orientation.

        Parameters:
            curr_roll: Current roll data
            curr_pitch Current pitch data
            curr_z_pos: Current z position
            desired_roll: Desired roll position
            desired_pitch: Desired pitch position
            desired_z_pos: Desired z (depth) position

        Returns:
            error: The roll, pitch and depth error
        '''
        #Calculate error for each degree of freedom
        error = [0, 0, 0, 0, 0, 0]
        error[0] = desired_roll - curr_roll
        roll_control = self.roll_pid_controller.control_step(error[0])

        error[1] = desired_pitch - curr_pitch
        pitch_control = self.pitch_pid_controller.control_step(error[1])

        #depth error
        error[2] = desired_z_pos - curr_z_pos
        z_control = self.z_pid_controller.control_step(error[2])

        #Write controls to thrusters
        #Set x, y, and yaw controls to zero since we don't care about the subs
        #heading or planar orientation for a simple depth move
        self.controlled_thrust(roll_control, pitch_control, 0, 0, 0, z_control, curr_z_pos)

        return error
