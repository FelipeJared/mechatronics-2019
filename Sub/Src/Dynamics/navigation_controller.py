
'''
Copyright 2019, David Pierce Walker-Howell, All rights reserved
Author: David Pierce Walker-Howell<piercedhowell@gmail.com>
Collaborator: Mohammad Shafi <ma.shafi99@gmail.com>
Last Modified 08/05/2019
Description: This module contains a highest level navigation controller for Perseverance.
                It contains multiple modes of control for the sub including
                thruster test mode, PID test mode, and Mission (Autonomous) Mode,
                and remote control mode..
'''
import sys
import os
import time
import csv

HELPER_PATH = os.path.join("..", "Helpers")
sys.path.append(HELPER_PATH)
import util_timer

PARAM_PATH = os.path.join("..", "Params")
sys.path.append(PARAM_PATH)
MECHOS_CONFIG_FILE_PATH = os.path.join(PARAM_PATH, "mechos_network_configs.txt")
from mechos_network_configs import MechOS_Network_Configs

MESSAGE_TYPE_PATH = os.path.join("..","..", "..", "Message_Types")
sys.path.append(MESSAGE_TYPE_PATH)
from desired_position_message import Desired_Position_Message
from thruster_message import Thruster_Message
from remote_command_message import Remote_Command_Message

from movement_pid import Movement_PID
from MechOS import mechos
from MechOS.simple_messages.float_array import Float_Array
from MechOS.simple_messages.bool import Bool
from MechOS.simple_messages.int import Int
import struct
import threading

import socket

MOVEMENT_AXIS = ["Roll", "Pitch", "Yaw", "X Pos.", "Y Pos.", "Depth"]

class Navigation_Controller(threading.Thread):
    '''
    This main Navigation controller for the sub. The navigation controller has 5 primary
    modes: Sub Killed, PID Tunning mode, Thruster Test Mode, Mission (Autonomous) Mode, and
    Remote control mode. The controller subscribers to the sensor data publishers and
    desired position publishers to plan its control using the pid controllers to move
    between positions.
    '''
    def __init__(self):
        '''
        Initialize the navigation controller. This includes getting parameters from the
        parameter server and initializing subscribers to listen for command messages and sensor data

        Parameters:
            N/A
        Returns:
            N/A
        '''

        threading.Thread.__init__(self)
        self.daemon = True

        #Get the mechos network parameters
        configs = MechOS_Network_Configs(MECHOS_CONFIG_FILE_PATH)._get_network_parameters()

        #MechOS node to connect movement controller to mechos network
        #The ip that the sub and mechoscore runs on are both 192.168.1.14
        self.navigation_controller_node = mechos.Node("NAVIGATION_CONTROLLER", '192.168.1.14', '192.168.1.14')

        #Subscribe to remote commands
        self.remote_control_subscriber = self.navigation_controller_node.create_subscriber("REMOTE_CONTROL_COMMAND", Remote_Command_Message(), self._read_remote_control, protocol="udp", queue_size=1)

        #Subscriber to change movement mode
        self.movement_mode_subscriber = self.navigation_controller_node.create_subscriber("MOVEMENT_MODE", Int(), self.__update_movement_mode_callback, protocol="tcp")

        #Update PID configurations button
        self.pid_configs_subscriber = self.navigation_controller_node.create_subscriber("UPDATE_PID_CONFIGS", Bool(), self.__update_pid_configs_callback, protocol="tcp")

        #Subscriber to get the desired position set by the user/mission controller.
        self.desired_position_subscriber = self.navigation_controller_node.create_subscriber("DESIRED_POSITION", Desired_Position_Message(), self.__unpack_desired_position_callback, protocol="tcp")

        #Subscriber to see if waypoint recording is enabled
        self.enable_waypoint_collection_subscriber = self.navigation_controller_node.create_subscriber("ENABLE_WAYPOINT_COLLECTION", Bool(), self.__update_enable_waypoint_collection, protocol="tcp")

        #Subscriber to listen for thrust messages from the thruster test widget
        self.thruster_test_subscriber = self.navigation_controller_node.create_subscriber("THRUSTS", Thruster_Message(), self.__update_thruster_test_callback, protocol="tcp")

        #Connect to parameters server
        self.param_serv = mechos.Parameter_Server_Client(configs["param_ip"], configs["param_port"])
        self.param_serv.use_parameter_database(configs["param_server_path"])

        #Subscriber to receive sensor data from the sensor driver node.
        self.nav_data_subscriber = self.navigation_controller_node.create_subscriber("SENSOR_DATA", Float_Array(6), self.__update_sensor_data, protocol="udp", queue_size=1)

        #Subscriber to commands from the GUI and Mission commanderto listen if the sub is killed.
        self.sub_killed_subscriber = self.navigation_controller_node.create_subscriber("KILL_SUB", Bool(), self._update_sub_killed_state, protocol="tcp")

        #Publisher to zero the NORTH/EAST position of the sub.
        self.zero_position_publisher = self.navigation_controller_node.create_publisher("ZERO_POSITION", Bool(), protocol="tcp")

        #Get navigation controller timing
        self.nav_time_interval = float(self.param_serv.get_param("Timing/nav_controller"))
        self.nav_timer = util_timer.Timer()

        #Initial movement mode to match GUI.
        #0 --> PID tuner
        #1 --> Thruster tester
        self.movement_mode = 0

        #Allow the naviagtion controller thread to run
        self.run_thread = True

        #1--> Thrusters are softkilled (by software)
        #0--> Thrusters are unkilled and can be commanded.
        self.sub_killed = 1

        #Initialize 6 degree of freedom PID movement controller used for the sub.
        #Primary control system for the sub
        self.pid_controller = Movement_PID()

        #Initialize current position [roll, pitch, yaw, north_pos, east_pos, depth]
        self.current_position = [0, 0, 0, 0, 0, 0]
        self.pos_error = [0, 0, 0, 0, 0, 0] #errors for all axies

        #Initialize desired position [roll, pitch, yaw, north_pos, east_pos, depth]
        self.desired_position = [0, 0, 0, 0, 0, 0]

        #Set up a thread to listen to a requests from GUI/mission_commander.
        # This includes movement mode, desired_position, new PID values, and sub killed command.
        self.command_listener_thread = threading.Thread(target=self._command_listener)
        self.command_listener_thread.daemon = True
        self.command_listener_thread_run = True
        self.command_listener_thread.start()

        #A thread to update the GUI/mission commander on the current position of the sub
        # and the current PID errors if the sub is in PID tunning mode
        self.update_command_thread = threading.Thread(target=self._update_command)
        self.update_command_thread.daemon = True
        self.update_command_thread_run = True
        self.update_command_thread.start()

        self.remote_commands = [0.0, 0.0, 0.0, 0.0, 0]
        self.waypoint_file = None
        self.enable_waypoint_collection = False

        self.daemon = True

        print("[INFO]: Sub Initially Killed")

    def _update_sub_killed_state(self, killed_state):
        '''
        The callback function to update the sub_killed state if the sub kill/unkill
        button is pressed. Updates the self.sub_killed attribute
        Parameters:
            killed_state: Raw byte (representing a boolean) for if the sub should
                            be killed or unkilled.
        Returns:
            N/A
        '''

        self.sub_killed = killed_state
        print("[INFO]: Sub Killed:", bool(self.sub_killed))

    def __update_sensor_data(self, sensor_data):
        '''
        Callback function of the SENSOR_DATA subscriber to receive the current
        position of the sub (which is the sensor data).

        Parameters:
            sensor_data: The roll, pitch, yaw, North pos, East pos, and Depth of the
            sub.
        Returns:
            N/A
        '''
        self.current_position = sensor_data

    def __update_movement_mode_callback(self, movement_mode):
        '''
        The callback function to select which movement controller mode is being used.
        It does this by setting the movment_mode class attribute. Updates the self.movement_mode
        attribute.
        Parameters:
            movement_mode: Raw byte of the mode.
        Returns:
            N/A
        '''
        self.movement_mode = movement_mode
        if(self.movement_mode == 0):
            print("[INFO]: Movement mode selected: PID Tuner Mode.")
            self.pid_values_update_freeze = False

            #SET TRUE IF YOU WANT TO GRAPHICALLY OBSERVE THE PID ERRORS IN THE GUI.
            self.update_pid_errors = False
            self.remote_hold_depth_state = False

        elif(self.movement_mode == 1):
            print("[INFO]: Movement mode selected: Thruster Test Mode")
            self.pid_values_update_freeze = True
            self.update_pid_errors = False
            self.remote_hold_depth_state = False

        elif(self.movement_mode == 2):
            print("[INFO]: Movement mode selected: Remote Control Mode")
            self.remote_control_listen = True
            self.pid_values_update_freeze = True
            self.update_pid_errors = False

        elif(self.movement_mode == 3):
            print("[INFO]: Movement mode selected: Autonomous Mode")
            self.remote_control_listen = False
            self.pid_values_update_freeze = True
            self.update_pid_errors = False

    def __update_pid_configs_callback(self, misc):
        '''
        The callback function to update the pid configuration if the save button
        is pressed. Calls the update pid values function of movement_pid.py.
        Parameters:
            misc: This parameter is not passed anything of value, because if this function
                    is called then it should just update the PID's.
        Returns:
            N/A
        '''
        self.pid_controller.set_up_PID_controllers()

    def _read_remote_control(self, remote_commands):
        '''
        The callback function to read the remote commmands from the
        REMOTE_CONTROL_COMMAND publisher to drive the sub in remote
        control mode.
        '''

        #Remote commands [yaw, x, y, depth, hold_depth?, record_waypoint?]
        self.remote_commands = remote_commands
        #Record a waypoint if waypoint collection is enabeled and the A button on
        #remote is pressed.
        if(self.enable_waypoint_collection and self.remote_commands[5]):
            [north_pos, east_pos, depth] = self.current_position[3:]
            print("[INFO]: Saving waypoint: Num %d, North Pos: %0.2fft, East Pos: %0.2fft, Depth: %0.2fft" \
                    % (self.current_waypoint_number, north_pos, east_pos, depth))
            self.waypoint_csv_writer.writerow([self.current_waypoint_number, north_pos, east_pos, depth])
            self.current_waypoint_number += 1

        #Zero position if the X button is pressed.
        if(self.remote_commands[6]):
            self.zero_position_publisher.publish(True)


    def __update_enable_waypoint_collection(self, enable_waypoint_collection):
        '''
        The callback function to see if the GUI is asking to enable/disable collecting
        waypoints mode.

        Parameters:
            enable_waypoint_collection: A boolean to set if the waypoint collection should
            be enabled. If enabled, then waypoints can be written to the set waypoint file.
        Returns:
            N/A
        '''
        #self.enable_waypoint_collection = struct.unpack('b', enable_waypoint_collection)[0]
        self.enable_waypoint_collection = enable_waypoint_collection
        waypoint_file = self.param_serv.get_param("Missions/waypoint_collect_file") #Get the waypoint save file

        if(self.enable_waypoint_collection):
            #Close a waypoint file if it is already open.
            if(self.waypoint_file != None):
                self.waypoint_file.close()

            self.waypoint_file = open(waypoint_file, 'w')
            self.waypoint_csv_writer = csv.writer(self.waypoint_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            self.current_waypoint_number = 0
            print("[INFO]: Waypoint collection enabled. Saving waypoints to file: %s" % waypoint_file)
        else:
            if(self.waypoint_file != None):
                self.waypoint_file.close()
            print("[INFO]: Waypoint collection disabled.")


    def _command_listener(self):
        '''
        The thread to run to update requests from the gui or mission commaner for changes in the movement mode,
        sub_killed, sensor data, desired position.

        Parameters:
            N/A
        Returns:
            N/A
        '''
        while self.command_listener_thread_run:
            try:
                #Check all subscribers for new data to be updated.
                self.navigation_controller_node.spin_once()

            except Exception as e:
                print("[ERROR]: Could not properly recieved messages in command listener. Error:", e)

            time.sleep(0.01)

    def _update_command(self):
        '''
        This thread publishes the sensor data which gives the current naviagtion position to
        the GUI and Mission Commander. It also sends the current PID error if in PID tuning mode.
        
        Parameters:
            N/A
        Returns:
            N/A
        '''
        while(self.update_command_thread_run):
            try:
                x = 1
            except Exception as e:
                print("[ERROR]: Could not correctly send data from navigation controller. Error:", e)
            time.sleep(0.1)

    def __unpack_desired_position_callback(self, desired_position):
        '''
        The callback function to unpack the desired position proto message received
        through MechOS.
        Parameters:
            desired_position_proto: Protobuf of type DESIRED_POS to unpack
        Returns:
            N/A
        '''
        self.desired_position = desired_position

        print("\n\nNew Desire Position Recieved:")
        for index, dp in enumerate(self.desired_position):
            print("%s: %0.2f" % (MOVEMENT_AXIS[index], dp), end='')
        print("")


    def __update_thruster_test_callback(self, thrusts):
        '''
        The callback function to unpack and write thrusts to each thruster for
        thruster test.
        Parameters:
            thruster_proto: Protobuf of type Thrusters.
        Returns:
            N/A
        '''

        print("\nTesting Thrusters")
        for index, value in enumerate(thrusts):
            print("Thruster %d: %d%% " % (index, value),end='')
        print("")
        self.pid_controller.simple_thrust(thrusts)


    def run(self):
        '''
        Runs the movement control in the control mode specified by the user. The
        different modes of control are as follows.
            '0' --> PID tunning mode.
            '1' --> Thruster test mode.
        Parameters:
            N/A
        Returns:
            N/A
        '''
        current_position = [0, 0, 0, 0, 0, 0]
        self.nav_timer.restart_timer()

        while(1):
            nav_time = self.nav_timer.net_timer()

            if(nav_time < self.nav_time_interval):
                time.sleep(self.nav_time_interval - nav_time)
                self.nav_timer.restart_timer()
            else:
                self.nav_timer.restart_timer()

            if(self.sub_killed == 1):
                #Turn off all thrusters
                self.pid_controller.simple_thrust([0, 0, 0, 0, 0, 0, 0, 0])

            #PID Depth, pitch, roll Tunning Mode
            #In PID depth, pitch, roll tunning mode, only roll pitch and depth are used in
            #the control loop perfrom a simpe Depth PID move. north_pos, east_pos, and
            #yaw are ignored.
            elif self.movement_mode == 0:

                #----ADVANCE MOVE (ALL 6 DEGREES OF FREEDOMW)--------------------------
                self.pos_error = self.pid_controller.advance_move(self.current_position, self.desired_position)

            #THRUSTER test mode.
            elif self.movement_mode == 1:

                continue
            #Remote navigation (using PID controllers)
            elif self.movement_mode == 2: #SWITCHED MOVMENT MODES FOR TESTING CONTROLLER, REVERT BACK

                self.pid_controller.remote_move(self.current_position, self.remote_commands)

            #Autonomous Mission mode. Mission is live and running.
            elif self.movement_mode == 3:

                self.pid_controller.advance_move(self.current_position, self.desired_position)

if __name__ == "__main__":

    #sensor_driver = Sensor_Driver()
    navigation_controller = Navigation_Controller()
    #sensor_driver.start()
    navigation_controller.run()
