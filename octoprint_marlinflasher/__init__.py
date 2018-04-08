# coding=utf-8
from __future__ import absolute_import
import flask
import json
import os
import octoprint.plugin
import httplib2
import octoprint.server.util.flask
from octoprint.server import admin_permission
from octoprint.events import Events
from subprocess import call, Popen, PIPE
import threading
import time
import re

class MarlinFlasherPlugin(octoprint.plugin.BlueprintPlugin,
                           octoprint.plugin.TemplatePlugin,
                           octoprint.plugin.AssetPlugin,
                           octoprint.plugin.SettingsPlugin,
                           octoprint.plugin.EventHandlerPlugin,
                           octoprint.plugin.StartupPlugin):
    
    def __init__(self):
        self.templates = ('Configuration.h', 'Configuration_adv.h', 'pins_RUMBA.h')
        self.depList = ['avr-libc', 'avrdude', 'make', 'cmake']
        self.hardwareLibs = ['SPI', 'Wire']
        self.libs = ['U8glib']
        self.depInstalled = False
        
    def on_startup(self, host, port):
        self.depInstalled = self.check_dep()
        self.getDefLib()
               
    def on_after_startup(self):
        dataFolder = self.get_plugin_data_folder()
        profileFolder = dataFolder + '/profiles'
        defaultProfileFolder = self._basefolder + '/default_profiles'
              
        if not os.path.isdir(profileFolder):
            os.mkdir(profileFolder)
            #call(['cp', '-a', defaultProfileFolder + '/.', profileFolder + '/' ])
        
    @octoprint.plugin.BlueprintPlugin.route("/make", methods=["POST"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def make_marlin(self):
        
        avrdudePath = '/usr/bin/avrdude'
        selectedPort = flask.request.json['selected_port'] if flask.request.json.has_key('selected_port') else ''
        profileId = flask.request.json['profileId']
        dataFolder = self.get_plugin_data_folder()
        #buildFolder = dataFolder + '/tmp'
        #hexPath = buildFolder + '/Marlin.hex'
        libPath = self._basefolder + '/lib'
        arduinoLibPath = libPath + '/arduino-1.6.11'
        makeFilePath = libPath + '/Makefile'
        
        
        profile = self.getProfileFromId(profileId)
        repoPath = self.getRepoNamePath(profile['url'])
        marlinFolder = repoPath + '/Marlin'
        
        cmakeFolder = repoPath + '/buildroot/share/cmake'
        buildFolder = repoPath + '/build'
        hexPath = buildFolder + '/Marlin.hex'
               
        
        if self._printer.is_printing() or self._printer.is_paused():
            self._sendStatus(line='Printer is busy! Flashing Aborted!', stream='stderr')
            return flask.make_response("Error.", 500)
        
        
        self._sendStatus(line='Checking out selected branch...', stream='message')
        
        self.execute(['git', 'checkout', '-f', profile['branch']], cwd= repoPath)
        
            
        if profile['url'] in self.getAutoUpdateList():
            self._sendStatus(line='Updating selected branch...', stream='message')
            self.execute(['git', 'fetch', '--all'], cwd= repoPath)
#             self.execute(['git', 'reset', '--hard', profile['branch']], cwd= repoPath)
            self.addDefineLibEntry(profile['url'], profile['branch'])
        
        self._sendStatus(line='Writing configuration..........', stream='message')
        
        self.writeMarlinConfig(profile, marlinFolder)

        self._sendStatus(line='Building Marlin................', stream='message')
        
        if not os.path.isdir(buildFolder):
            os.mkdir(buildFolder)
        
#         cmakecmd = ['cmake', libPath, '-DBOARD_VARIANT=mega', '-DMCU=atmega2560', '-DF_CPU=16000000L', '-DUPLOAD_PORT=' + selectedPort,
#                       '-DMARLIN_SRC_PATH=' + marlinFolder + '/Marlin', '-DARDUINO_SDK_PATH=' + arduinoLibPath ]
#         
#         self._sendStatus(line=' '.join(cmakecmd), stream='message') 
        
        self.execute(['cmake', libPath, '-DBOARD_VARIANT=mega', '-DMCU=atmega2560', '-DF_CPU=16000000L', '-DUPLOAD_PORT=' + selectedPort,
                      '-DMARLIN_SRC_PATH=' + marlinFolder, '-DARDUINO_SDK_PATH=' + arduinoLibPath, '-DHARDWARE_LIBS=' + ';'.join(self.hardwareLibs), '-DLIBS=' + ';'.join(self.libs) ], cwd=buildFolder)
        
        self.execute(['make', '-j4'], cwd=buildFolder)
        
        
        if os.path.exists(hexPath):

            self._sendStatus(line='Marlin.hex found! Proceeding to flash with avrdude.', stream='message')
        
            #self._printer.disconnect()   
            
            avrdude_command = [avrdudePath, "-v", "-p", "m2560", "-c", "wiring", "-P", selectedPort, "-U", "flash:w:" + hexPath + ":i", "-D"]
             
            #self._sendStatus(line='Command: ' + ' '.join(avrdude_command), stream='stdout')
            
            if selectedPort in ('VIRTUAL', 'AUTO', ''): 
                
                self._sendStatus(line='Selected port: ' + selectedPort + ' can not be used!', stream='stderr')
            else: 
                self._printer.disconnect() 
                self.execute(avrdude_command, cwd=os.path.dirname(avrdudePath))        
                self._printer.connect(port=selectedPort)
                
            
         
        else:   
            self._sendStatus(line='Something went wrong. Hex file does not exist!', stream='stderr')
            
        self._sendStatus(line='Deleting hex file', stream='message')
        
        if os.path.exists(hexPath):
            os.remove(hexPath)
#         
#         if os.path.exists(buildFolder + '/Marlin.eep'):
#             os.remove(buildFolder + '/Marlin.eep')
#         
#         if os.path.exists(buildFolder + '/Marlin.elf'):
#             os.remove(buildFolder + '/Marlin.elf')
        
             
        
        #self.execute(['make', 'clean', '-f', makeFilePath, 'BUILD_DIR=' + buildFolder, 'ARDUINO_LIB_DIR=' + arduinoLibPath], cwd=marlinFolder)
        #self.execute(['make', 'clean'], cwd=buildFolder)
 
        return flask.make_response("", 204)
          
    def writeMarlinConfig(self, profile, marlinFolder):
     
        defReg = re.compile('\s*(\/\/)?\s*#define\s+(\S+)\s*(.*)')
            
        for template in self.templates:
            with open(marlinFolder + '/' + template, 'r') as f:
                templateFileBuffer = f.readlines()

            targFile = open(marlinFolder + '/' + template, 'w')  
                            
            for line in templateFileBuffer:
                defRes = defReg.search(line)
                
                if defRes:
                    identifier = defRes.group(2)
                                        
                    for param in profile['define']:
                        if param['identifier'] == identifier:
                            enabled = '' if param['enabled'] else '//'
                            targFile.write(enabled + '#define ' + param['identifier'] + ' ' + param['value'] + ' //Modified by MarlinFlasher Plugin\n')
                            break
                    else:
                        targFile.write(line)
                    
                else:
                    targFile.write(line)
                           
           
            targFile.flush()
            targFile.close()
             
    def getProfileFromId(self, profileId):
        dataFolder = self.get_plugin_data_folder()
        profilePath = dataFolder + '/profiles/' + profileId
        with open(profilePath, 'r+b') as f:
                profile = eval(f.read())['profile']
                
        return profile       
      
    @octoprint.plugin.BlueprintPlugin.route("/check_dep", methods=["POST"])
    def getIsDepInstalled(self):
        return flask.jsonify(isInstalled=self.depInstalled)
    
    def check_dep(self):
        #cache = apt.Cache()
        
        def checkInstalled(package):
            res = Popen(['dpkg', '-s', package], stdout=PIPE)
            
            return 'Status: install ok installed' in res.communicate()[0]
            
        isInstalled = True
        
        for packageName in self.depList:
            try:
                isInstalled = isInstalled and checkInstalled(packageName)
            except:
                isInstalled = False
                    
        return isInstalled
    
    @octoprint.plugin.BlueprintPlugin.route("/install", methods=["POST"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def install_dep(self):
        
        installCommand = ['sudo', 'apt-get', 'install', '-y'] + self.depList
        self._sendStatus(line='Command: ' + ' '.join(installCommand), stream='stdout')
        
        self.execute(installCommand)
        
        self.depInstalled = self.check_dep()
        
        return flask.make_response("Ok.", 200)
    
    @octoprint.plugin.BlueprintPlugin.route("/firmwareprofiles", methods=["GET"])
    def getProfileList(self):
        dataFolder = self.get_plugin_data_folder()
        profile_folder = dataFolder + '/profiles'
        
        if not os.path.isdir(profile_folder):
            os.mkdir(profile_folder)
        
        _,_,fileList = os.walk(profile_folder).next()
        
        returnDict = {}
        
        for pFile in fileList:
            with open(profile_folder +'/'+ pFile, 'r+b') as f:
                profile = eval(f.read())['profile']
                returnDict[profile['id']] = profile 

                
        return flask.jsonify(profiles=returnDict)
    
    @octoprint.plugin.BlueprintPlugin.route("/firmwarerepos", methods=["GET"])
    def getRepoList(self):
             
        defineLib = self.getDefLib()       
                
        repos = self.getRepos()
                
        return flask.jsonify(repos=repos, defineLib = defineLib)
    
    def getDefLib(self):
        dataFolder = self.get_plugin_data_folder()
        settingsFolder = dataFolder + '/settings'
        
        if not os.path.isdir(settingsFolder):
            os.mkdir(settingsFolder)
        
        defLibFile = settingsFolder + '/deflib'
        
        if os.path.isfile(defLibFile):            
            with open(defLibFile, 'r+b') as f:
                currentDefLib = eval(f.read())
        else:
            currentDefLib = {}
            
        if currentDefLib.has_key('version'):
            if currentDefLib['version'] == self._plugin_version:
                return currentDefLib
             
        self.addAllRepoToDefLib()
             
        if os.path.isfile(defLibFile):            
            with open(defLibFile, 'r+b') as f:
                currentDefLib = eval(f.read())
        else:
            currentDefLib = {}
            
        return currentDefLib
    
    def addAllRepoToDefLib(self):
        dataFolder = self.get_plugin_data_folder()        
        defLibFile = dataFolder + '/settings/deflib'
        if os.path.isfile(defLibFile):
            os.remove(defLibFile)
            
        for repo in self.getRepos():
            self.addRepoToDefLib(repo['repoUrl'])
       
    def addRepoToDefLib(self, url):
        
        gitInfo = self.getGitInfo(self.getRepoNamePath(url))
        
        for branch in gitInfo['branchList']:
            self.addDefineLibEntry(url, branch)
            
    def removeRepoFromDefLib(self, url):
        dataFolder = self.get_plugin_data_folder()
        settingsFolder = dataFolder + '/settings'
        
        if not os.path.isdir(settingsFolder):
            return
        
        defLibFile = settingsFolder + '/deflib'
        
        if os.path.isfile(defLibFile):            
            with open(defLibFile, 'r+b') as f:
                currentDefLib = eval(f.read())
        else:
            return
        
        if currentDefLib.has_key('repos'):
            currentDefLib['repos'].pop(url, None)
    
        
        
        with open(defLibFile, 'w+b') as f:
            f.write(str(currentDefLib))
        
    def addDefineLibEntry(self, url, branch):
        defReg = re.compile('\s*(\/\/)?\s*#define\s+(\S+)\s*(.*)')
        
        dataFolder = self.get_plugin_data_folder()
        settingsFolder = dataFolder + '/settings'
        
        if not os.path.isdir(settingsFolder):
            os.mkdir(settingsFolder)
        
        defLibFile = settingsFolder + '/deflib'
        
        if os.path.isfile(defLibFile):            
            with open(defLibFile, 'r+b') as f:
                currentDefLib = eval(f.read())
        else:
            currentDefLib = {}
        
        try:
            repoPath = self.getRepoNamePath(url)
            marlinFolder = repoPath + '/Marlin'
            self.execute(['git', 'checkout', '-f', branch], cwd= repoPath)
            #self.execute(['git', 'reset', '--hard', branch], cwd= repoNamePath)
        except:
            return
        
        if not os.path.exists(marlinFolder):
            return
        
        
        if not currentDefLib.has_key('defines'):
            currentDefLib['defines'] = []
            
        if not currentDefLib.has_key('repos'):
            currentDefLib['repos'] = {}
            
        if not currentDefLib['repos'].has_key(url):
            currentDefLib['repos'][url] = {}
            
        currentDefLib['repos'][url][branch] = []
       
        for template in self.templates:
            if not os.path.isfile(marlinFolder + '/' + template):
                return
            tempFile = open(marlinFolder + '/' + template, 'r')
            
            
            for line in tempFile.readlines():
                defRes = defReg.search(line)
                
                if defRes:
                    identifier = defRes.group(2)
                    value = defRes.group(3).split('//')[0].split('/*')[0].strip()
                    enabled = defRes.group(1) == None
                    
                    defTmp = {'identifier': identifier, 'value': value, 'enabled': enabled}
                    
                    if defTmp not in currentDefLib['defines']:
                        currentDefLib['defines'].append(defTmp.copy())
                        
                    if identifier not in map(lambda x: currentDefLib['defines'][x]['identifier'], currentDefLib['repos'][url][branch]):
                        
                        currentDefLib['repos'][url][branch].append(currentDefLib['defines'].index(defTmp))

                    elif enabled:
                        for i in range(len(currentDefLib['repos'][url][branch])):
                            if currentDefLib['defines'][currentDefLib['repos'][url][branch][i]]['identifier'] == identifier:
                                currentDefLib['repos'][url][branch][i] = currentDefLib['defines'].index(defTmp)
                                
                        
            
            tempFile.close()
        
        currentDefLib['version'] = self._plugin_version
        
        with open(defLibFile, 'w+b') as f:
            f.write(str(currentDefLib))
    
    @octoprint.plugin.BlueprintPlugin.route("/firmwareprofiles", methods=["POST"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def addNewProfile(self):
        dataFolder = self.get_plugin_data_folder()
        profile_folder = dataFolder + '/profiles'
        
        if not os.path.isdir(profile_folder):
            os.mkdir(profile_folder)
            
        profile_id = flask.request.json['profile']['id']
        
        profile_file = open(profile_folder + '/' + profile_id, 'w+b')
        
        profile_file.write(str(flask.request.json))
        profile_file.flush()
        profile_file.close()
        
        
#         
#         print '****************Output from addNewProfile:*************************'
#         print flask.request.json
#         for i in flask.request.json['profile']:
#             print i
#         print type(flask.request.json)
       
       
        return flask.make_response("", 204)            
 
    @octoprint.plugin.BlueprintPlugin.route("/import_profile", methods=["POST"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def importProfile(self):
        
        inputName = "file"
        inputUploadPath = inputName + "." + self._settings.global_get(["server", "uploads", "pathSuffix"])

        if inputUploadPath not in flask.request.values:       
            return flask.make_response("Error.", 500)

        uploadProfilePath = flask.request.values[inputUploadPath]
       
        try:
            with open(uploadProfilePath, 'r+b') as f:
                profile = eval(f.read())['profile']
        except:
            return flask.make_response("Error.", 415)
   
       
        return flask.jsonify(profile)     
        
    @octoprint.plugin.BlueprintPlugin.route("/firmwareprofiles/<string:identifier>", methods=["DELETE"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def deleteProfile(self, identifier):
        dataFolder = self.get_plugin_data_folder()
        file_path = dataFolder + '/profiles/' + identifier
           
        if os.path.isfile(file_path):
            os.remove(file_path)
                 
        return flask.make_response("", 204)
    
    @octoprint.plugin.BlueprintPlugin.route("/firmwareprofiles/<string:identifier>", methods=["PATCH"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def updateProfile(self, identifier):
        dataFolder = self.get_plugin_data_folder()
        profile_folder = dataFolder + '/profiles'
        
        if not os.path.isdir(profile_folder):
            os.mkdir(profile_folder)
            
        profile_id = flask.request.json['profile']['id']
        
        profile_file = open(profile_folder + '/' + profile_id, 'w+b')
        
        profile_file.write(str(flask.request.json))
        profile_file.flush()
        profile_file.close()
        
        
        
#         print '****************Output from addNewProfile:*************************'
#         print flask.request.json
#         for i in flask.request.json['profile']:
#             print i
#         print type(flask.request.json)
       
       
        return flask.make_response("", 204)
    
    @octoprint.plugin.BlueprintPlugin.route("/updateRepos/", methods=["POST"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def saveRepos(self):
        repoList = flask.request.json['repoUrlList']
        
        self._sendStatus(line='Checking if there are any changes.', stream='message')
        
        for exsitingRepo in self.getRepos():
            if exsitingRepo['repoUrl'] not in map(lambda x: x['repoUrl'], repoList):
                repoUserFolder = self.getRepoUserPath(exsitingRepo['repoUrl'])
                #print 'Going to delete:', exsitingRepo['repoUrl']
                self.execute(['rm', '-rfv', self.getRepoName(exsitingRepo['repoUrl'])], cwd= repoUserFolder)
                self.removeRepoFromDefLib(exsitingRepo['repoUrl'])
        
        for repo in repoList:
            
            if repo['add']:
                if self.isValidGithubRepo(repo['repoUrl']):
                    repoUserFolder = self.getRepoUserPath(repo['repoUrl'])
                    
                    self.execute(['git', 'clone', '-v', '--progress', repo['repoUrl']], cwd= repoUserFolder)
                    
                    self.addRepoToDefLib(repo['repoUrl'])
        
        self.saveAutoUpdateList(repoList)  
       
        return flask.make_response("", 204)
    
    @octoprint.plugin.BlueprintPlugin.route("/updateRepos/", methods=["PATCH"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def updateRepos(self):
       
        repo = flask.request.json['repo']
        repoUrl = repo['repoUrl']
        repoNamePath = self.getRepoNamePath(repoUrl)
        
        self._sendStatus(line= 'Pull changes from remote:' + repoUrl, stream='stdout')
        
        self.execute(['git', 'fetch', '--all'], cwd= repoNamePath)
        
        self._sendStatus(line= 'Updating define library', stream='stdout')
        
        gitInfo = self.getGitInfo(repoNamePath)
        
        for branch in gitInfo['branchList']:
            self._sendStatus(line= 'Updating: ' + branch, stream='message')
#             self.execute(['git', 'checkout', '-f', branch], cwd= repoNamePath) # Throw away any changes before pull
#             self.execute(['git', 'reset', '--hard', branch], cwd= repoNamePath)
            self.addDefineLibEntry(repoUrl, branch)
        
        
        return flask.make_response("", 204)
    
    @octoprint.plugin.BlueprintPlugin.route("/cleanRepo/", methods=["POST"])
    @octoprint.server.util.flask.restricted_access
    @octoprint.server.admin_permission.require(403)
    def cleanRepo(self):
       
        repo = flask.request.json['repo']
        repoUrl = repo['repoUrl']
        repoNamePath = self.getRepoNamePath(repoUrl)
        
        #self._sendStatus(line= 'Pull changes from remote:' + repoUrl, stream='stdout')
        
        #self.execute(['git', 'fetch'], cwd= repoNamePath)
        
        #self._sendStatus(line= 'Updating define library', stream='stdout')
        
        gitInfo = self.getGitInfo(repoNamePath)
        
        self.execute(['git', 'clean', '-fxd'], cwd= repoNamePath) # Clean repo
        
        return flask.make_response("", 204)
    
            
    def getRepos(self):
        repo_folder = self.getRepoPath()
            
        repoUserList = os.listdir(repo_folder)
        repoList = []
        for repoUser in repoUserList:
            for repo in os.listdir(repo_folder + '/' + repoUser):
                gitInfo = self.getGitInfo(repo_folder + '/' + repoUser + '/' + repo)
                if not gitInfo == None:
                    gitInfo['add'] = False
                    if gitInfo['repoUrl'] in self.getAutoUpdateList():
                        gitInfo['autoUpdate'] = True
                    repoList.append(gitInfo) 
                
        return repoList
    
    def saveAutoUpdateList(self, repoList):
        dataFolder = self.get_plugin_data_folder()
        settingsFolder = dataFolder + '/settings'
        
        if not os.path.isdir(settingsFolder):
            os.mkdir(settingsFolder)
        
        autoFile = settingsFolder + '/autoReg'
        
        autoList = []
        
        for repo in repoList:
            if repo['autoUpdate'] == True:
                autoList.append(repo['repoUrl'])
                
        with open(autoFile, 'w') as f:
            f.write(str(autoList))
    
    def getAutoUpdateList(self):
        dataFolder = self.get_plugin_data_folder()
        settingsFolder = dataFolder + '/settings'
        
        if not os.path.isdir(settingsFolder):
            os.mkdir(settingsFolder)
        
        autoFile = settingsFolder + '/autoReg'
        
        autoList = []
        if os.path.isfile(autoFile):        
            with open(autoFile, 'r') as f:
                autoList = eval(f.read())
        
        return autoList
    
    def getGitInfo(self, path):
        # * remote origin
        #   Fetch URL: https://github.com/tohara/OctoPrint-MarlinFlasher.git
        #   Push  URL: https://github.com/tohara/OctoPrint-MarlinFlasher.git
        #   HEAD branch: (not queried)
        #   Remote branches: (status not queried)
        #     RC6
        #     RC6dev
        #     RC7
        #     dev
        #   Local branch configured for 'git pull':
        #     RC6 merges with remote RC6
        #   Local ref configured for 'git push' (status not queried):
        #     (matching) pushes to (matching)

        gitCall = Popen(['git', 'remote', 'show', '-n', 'origin'], stdout=PIPE, cwd=path)
        
        res, err = gitCall.communicate()
        
        #print 'Form getGitInfo: ', res, err, path
        
        retDict = {}
        retDict['repoUrl'] = ''
        retDict['branchList'] = []
        #branchTrigger = False
               
        
        for line in res.split('\n'):
            if 'Fetch URL:' in line:
                retDict['repoUrl'] = line.replace('Fetch URL:', '').strip()
#              
#             if 'Local branch' in line: 
#                 branchTrigger = False
#                  
#             if branchTrigger:
#                 retDict['branchList'].append(line.strip())
#              
#              
#             if 'Remote branch' in line: 
#                 branchTrigger = True

        gitCall = Popen(['git', 'branch', '-r'], stdout=PIPE, cwd=path)
        res, err = gitCall.communicate()
        
        for line in res.strip().split('\n'):
            retDict['branchList'].append(line.strip().split(' ')[0])
            
            
         
        gitCall = Popen(['git', 'tag'], stdout=PIPE, cwd=path)
        res, err = gitCall.communicate()
        
        for line in res.strip().split('\n'):
            retDict['branchList'].append('tags/' + line.strip())
        
           
        return retDict if self.isValidGithubRepo(retDict['repoUrl'], False) else None
    
    def isValidGithubRepo(self, repoUrl, checkOnline=True):
        
        valid = False
        try:
            if 'https://' == repoUrl[0:8] and '.git' == repoUrl[-4:]:
                if checkOnline:
                    h = httplib2.Http()
                    resp = h.request(repoUrl)
                    valid = int(resp[0]['status']) < 400
                else:
                    valid = True
        except:
            valid = False
            
        if not valid:
            self._sendStatus(line= repoUrl + ' is not a valid Github repo or no internet connection.',stream='stderr')
            
        return valid
    
    def getRepoUser(self, repoUrl):
        if not ('https://' == repoUrl[0:8] and '.git' == repoUrl[-4:]):
            raise self.RepoUrlException('The repo URL is wrong format!')
        
        try:
            return repoUrl.replace('https://', '').split('/')[1]
        except Exception:
            raise self.RepoUrlException('The repo URL is wrong format!')
    
    def getRepoPath(self):
        dataFolder = self.get_plugin_data_folder()
        repoFolder = dataFolder + '/repos'
        
        if not os.path.isdir(repoFolder):
            os.mkdir(repoFolder)
            
        return repoFolder
            
    def getRepoUserPath(self, repoUrl):
                       
        repoUserPath = self.getRepoPath() + '/' + self.getRepoUser(repoUrl)
        
        if not os.path.isdir(repoUserPath):
            os.mkdir(repoUserPath)
        
        return repoUserPath
    
    def getRepoName(self, repoUrl):
        
        if not ('https://' == repoUrl[0:8] and '.git' == repoUrl[-4:]):
            raise self.RepoUrlException('The repo URL is wrong format!')
        
        try:
            return repoUrl.replace('https://', '').split('/')[2].replace('.git', '').strip()
        except Exception:
            raise self.RepoUrlException('The repo URL is wrong format!')
    
    def getRepoNamePath(self, repoUrl):
        
        repoNamePath = self.getRepoUserPath(repoUrl) + '/' + self.getRepoName(repoUrl)
#         if not os.path.isdir(repoNamePath):
#             os.mkdir(repoNamePath)
        
        return repoNamePath
    
    class RepoUrlException(Exception):
        pass

    def execute(self, args, **kwargs):
        
        pswd = kwargs.pop('pswd', None)
        res = Popen(args, stdout=PIPE, stderr=PIPE, universal_newlines=True, **kwargs)
        
        if pswd:
            res.stdin.write(pswd + '\n')
            
        linesStdout = iter(res.stdout.readline, "")
        linesStderr = iter(res.stderr.readline, "")
        
        
        def stdoutListener():
            for line in linesStdout:
                #print 'stdout:', line
                self._sendStatus(line=line.replace('\n', ''), stream='stdout')
                
        def stderrListener():
            for line in linesStderr:
                #print 'stderr:', line
                self._sendStatus(line=line.replace('\n', ''), stream='stderr')
                
            
        
        stdoutThread = threading.Thread(target=stdoutListener)
        stdoutThread.daemon = False
        stdoutThread.start()
        
        stderrThread = threading.Thread(target=stderrListener)
        stderrThread.daemon = False
        stderrThread.start()
        
            
        #print 'Waiting for error thread'   
        stderrThread.join()
        #print 'Waiting for stdout thread' 
        stdoutThread.join()
        
                     
    
	##~~ SettingsPlugin mixin

    def get_settings_defaults(self):
        return dict(
			# put your plugin's default settings here
		)

	##~~ AssetPlugin mixin
    
    def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(
			js=["js/marlinflasher.js"],
			css=["css/marlinflasher.css"],
			less=["less/marlinflasher.less"]
		)

	##~~ Softwareupdate hook
    
    def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://github.com/foosel/OctoPrint/wiki/Plugin:-Software-Update
		# for details.
		return dict(
			marlinflasher=dict(
				displayName="Marlin Firmware Flasher",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_commit",
				user="tohara",
				repo="OctoPrint-MarlinFlasher",
                #branch="dev",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/tohara/OctoPrint-MarlinFlasher/archive/{target_version}.zip"
			)
		)
        
    def route_hook(self, server_routes, *args, **kwargs):
        from octoprint.server.util.tornado import LargeResponseHandler
        
        def mime_type_guesser(path):
            from octoprint.filemanager import get_mime_type
            return get_mime_type(path)

        return [
            (r"/export_profile/(.*)", LargeResponseHandler, dict(path=self.get_plugin_data_folder() + '/profiles',
                                                           as_attachment=True,
                                                           mime_type_guesser=mime_type_guesser))
                
           
        ]
    
    #~~ Extra methods
    
    def _sendStatus(self, line, stream):
        self._plugin_manager.send_plugin_message(self._identifier, dict(type="logline", line=line, stream=stream))



# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "MarlinFlasher"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = MarlinFlasherPlugin()
    

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.server.http.routes": __plugin_implementation__.route_hook
	}

