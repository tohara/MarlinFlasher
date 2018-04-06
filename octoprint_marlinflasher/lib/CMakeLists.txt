cmake_minimum_required(VERSION 2.8)

#====================================================================#
# Variables needed for support of all boards                         #
#====================================================================#

#set(BOARD_VARIANT mega)
#set(MCU atmega2560)
#set(F_CPU 16000000L)
#set(UPLOAD_PORT /dev/ttyACM0)
#set(MARLIN_SRC_PATH /home/tom/.octoprint/data/marlinflasher/repos/tohara/Marlin/Marlin)
#set(ARDUINO_SDK_PATH  /home/tom/3dprojects/OctoPrint/venv/lib/python2.7/site-packages/octoprint_marlinflasher/lib/arduino-1.6.11)
set(ARDUINO_VERSION 10611)
#set(HARDWARE_LIBS SPI;Wire)
#set(LIBS U8glib)

#====================================================================#
# Internal variables                                                 #
#====================================================================#
#cmake /home/tom/3dprojects/OctoPrint/venv/lib/python2.7/site-packages/octoprint_marlinflasher/lib 
#-DBOARD_VARIANT=mega 
#-DMCU=atmega2560 
#-DF_CPU=16000000L 
#-DUPLOAD_PORT= 
#-DMARLIN_SRC_PATH=/home/tom/.octoprint/data/marlinflasher/repos/tohara/Marlin/Marlin/Marlin 
#-DARDUINO_SDK_PATH=/home/tom/3dprojects/OctoPrint/venv/lib/python2.7/site-packages/octoprint_marlinflasher/lib/arduino-1.6.11

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_C_COMPILER   avr-gcc)
set(CMAKE_CXX_COMPILER avr-g++)
set(AVR_SIZE avr-size)
set(AVRDUDE avrdude)

set_property(GLOBAL PROPERTY RULE_MESSAGES OFF)


set(CMAKE_C_FLAGS "-Os -w -std=gnu11 -ffunction-sections -fdata-sections -MMD -mmcu=${MCU} -DF_CPU=${F_CPU} -DARDUINO=${ARDUINO_VERSION}" CACHE STRING "")
set(CMAKE_CXX_FLAGS "-Os -w -std=gnu++11 -fpermissive -fno-exceptions -ffunction-sections -fdata-sections -fno-threadsafe-statics -MMD -mmcu=${MCU} -DF_CPU=${F_CPU} -DARDUINO=${ARDUINO_VERSION}" CACHE STRING "")
set(CMAKE_EXE_LINKER_FLAGS "-w -Os -Wl,--gc-sections,--relax -lm -mmcu=${MCU}" CACHE STRING "")

MACRO(SUBDIRLIST result curdir)
  FILE(GLOB children RELATIVE ${curdir} ${curdir}/*)
  SET(dirlist "")
  FOREACH(child ${children})
    IF(IS_DIRECTORY ${curdir}/${child})
      LIST(APPEND dirlist ${child})
    ENDIF()
  ENDFOREACH()
  SET(${result} ${dirlist})
ENDMACRO()



#====================================================================#
# Set project                                                        #
#====================================================================#
project(Marlin C CXX)


file(GLOB_RECURSE SOURCES "${MARLIN_SRC_PATH}/*.c*")

#list(APPEND HARDWARE_LIBS SPI)
#list(APPEND HARDWARE_LIBS Wire)
#
#list(APPEND LIBS U8glib)


include_directories(${ARDUINO_SDK_PATH}/hardware/arduino/avr/variants/${BOARD_VARIANT})


# Core Lib
include_directories(${ARDUINO_SDK_PATH}/hardware/arduino/avr/cores/arduino)
file(GLOB_RECURSE CORE_SRC "${ARDUINO_SDK_PATH}/hardware/arduino/avr/cores/arduino/*.c*")

add_library(CORE ${CORE_SRC})

#set(DEBUG_LIBS ${HARDWARE_LIBS} CACHE STRING "ForDebug")
# Hardware Libs
SUBDIRLIST(HARDWARE_LIBS "${ARDUINO_SDK_PATH}/hardware/arduino/avr/libraries/")

foreach(LIB IN LISTS HARDWARE_LIBS)
		
        file(GLOB_RECURSE ${LIB}_HDR "${ARDUINO_SDK_PATH}/hardware/arduino/avr/libraries/${LIB}/*.h*")
       
        foreach(SRCF ${${LIB}_HDR})
                get_filename_component(INCDIR ${SRCF} DIRECTORY)
                include_directories(${INCDIR})
                
        endforeach()


        file(GLOB_RECURSE ${LIB}_SRC "${ARDUINO_SDK_PATH}/hardware/arduino/avr/libraries/${LIB}/*.c*")
        
        foreach(SRCF ${${LIB}_SRC})
			get_filename_component(INCDIR ${SRCF} DIRECTORY)
			include_directories(${INCDIR})
			
		endforeach()
	
        add_library(${LIB} ${${LIB}_SRC})

endforeach()

# Libraries

SUBDIRLIST(LIBS "${ARDUINO_SDK_PATH}/libraries/")


foreach(LIB IN LISTS LIBS)
        message(STATUS ${LIB})
        file(GLOB_RECURSE ${LIB}_SRC "${ARDUINO_SDK_PATH}/libraries/${LIB}/*.c*")
        
		foreach(SRCF ${${LIB}_SRC})
                get_filename_component(INCDIR ${SRCF} DIRECTORY)
                include_directories(${INCDIR})
                
           
        endforeach()
        
        file(GLOB_RECURSE ${LIB}_HDR "${ARDUINO_SDK_PATH}/libraries/${LIB}/*.h*")
     
		foreach(SRCF ${${LIB}_HDR})
			get_filename_component(INCDIR ${SRCF} DIRECTORY)
			include_directories(${INCDIR})
	
		endforeach()


        add_library(${LIB} ${${LIB}_SRC})

endforeach()


#====================================================================#
# Generate firmware (.hex file)                                      #
#====================================================================#


set(TARGET_NAME Marlin)

add_executable(${TARGET_NAME} ${SOURCES})

set_target_properties(${TARGET_NAME} PROPERTIES SUFFIX ".elf")

                
target_link_libraries(${TARGET_NAME} CORE ${LIBS} ${HARDWARE_LIBS} "-lm")


set(ARDUINO_OBJCOPY_EEP_FLAGS -O ihex -j .eeprom --set-section-flags=.eeprom=alloc,load --no-change-warnings --change-section-lma .eeprom=0 CACHE STRING "")
set(ARDUINO_OBJCOPY_HEX_FLAGS -O ihex -R .eeprom CACHE STRING "")

set(TARGET_PATH ${CMAKE_CURRENT_BINARY_DIR}/${TARGET_NAME})


add_custom_command(TARGET ${TARGET_NAME} POST_BUILD
                   COMMAND ${CMAKE_OBJCOPY}
                   ARGS    ${ARDUINO_OBJCOPY_HEX_FLAGS}
                           ${TARGET_PATH}.elf
                           ${TARGET_PATH}.hex
                   COMMENT "Generating HEX image"
                   VERBATIM)



set(AVRDUDE_ARGS -v)
list(APPEND AVRDUDE_ARGS -p${MCU}) 
list(APPEND AVRDUDE_ARGS -cwiring)
list(APPEND AVRDUDE_ARGS -P${UPLOAD_PORT})
list(APPEND AVRDUDE_ARGS -Uflash:w:${TARGET_PATH}.hex:i)
list(APPEND AVRDUDE_ARGS -D)

add_custom_target(upload
                ${AVRDUDE}
                ${AVRDUDE_ARGS}
                DEPENDS ${TARGET_NAME})
                
                 
set_directory_properties(PROPERTIES ADDITIONAL_MAKE_CLEAN_FILES "${TARGET_NAME}.hex")
                
                            
                   
add_custom_command(TARGET ${TARGET_NAME} POST_BUILD
                   COMMAND ${AVR_SIZE}
                   ARGS --mcu=${MCU} -C ${TARGET_NAME}.elf
                   COMMENT "Calculating AVR Memory Usage"
                   VERBATIM)  

      



