


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


## to call it from cammand lines
import sys
import os
from argparse import ArgumentParser
import shutil

# argument parsing and bookkeeping
from Losses import *

class training_base(object):
    
    def __init__(self, 
                 splittrainandtest=0.8,
                 useweights=False,
                 testrun=False):
        
        import matplotlib
        #if no X11 use below
        matplotlib.use('Agg')
        import imp
        try:
            imp.find_module('setGPU')
            import setGPU
        except ImportError:
            found = False
            
        
        import keras
                
        self.keras_inputs=[]
        self.keras_inputsshapes=[]
        self.keras_model=None
        self.train_data=None
        self.val_data=None
        self.startlearningrate=None
        self.optimizer=None
        self.trainedepoches=0
        self.compiled=False
        self.checkpointcounter=0
        
        parser = ArgumentParser('Run the training')
        parser.add_argument('inputDataCollection')
        parser.add_argument('outputDir')
        args = parser.parse_args()
        
        self.inputData = os.path.abspath(args.inputDataCollection)
        self.outputDir=args.outputDir
        # create output dir
        
        isNewTraining=True
        if os.path.isdir(self.outputDir):
            var = raw_input('output dir exists. To recover a training, please type "yes"\n')
            if not var == 'yes':
                raise Exception('output directory must not exists yet')
            isNewTraining=False     
        else:
            os.mkdir(self.outputDir)
        self.outputDir = os.path.abspath(self.outputDir)
        self.outputDir+='/'
        
        from DataCollection import DataCollection
        #copy configuration to output dir
        if isNewTraining:
            djsource= os.environ['DEEPJET']
            shutil.copytree(djsource+'/modules/models', self.outputDir+'models')
            shutil.copyfile(sys.argv[0],self.outputDir+sys.argv[0])

            
            
        self.train_data=DataCollection()
        self.train_data.readFromFile(self.inputData)
        self.train_data.useweights=useweights
        
        if testrun:
            self.train_data.split(0.02)
            
        self.val_data=self.train_data.split(splittrainandtest)
        
        self.train_data.writeToFile(self.outputDir+'trainsamples.dc')
        self.val_data.writeToFile(self.outputDir+'valsamples.dc')


        shapes=self.train_data.getInputShapes()
        
        self.keras_inputs=[]
        self.keras_inputsshapes=[]
        
        print(shapes)
        
        for s in shapes:
            self.keras_inputs.append(keras.layers.Input(shape=s))
            self.keras_inputsshapes.append(s)
            
        if not isNewTraining:
            self.loadModel(self.outputDir+'/KERAS_check_model_last.h5')
            self.trainedepoches=sum(1 for line in open(self.outputDir+'losses.log'))
        
        
    def __del__(self):
        del self.train_data
        del self.val_data
        
    def modelSet(self):
        return not self.keras_model==None
        
    def setModel(self,model,**modelargs):
        if len(self.keras_inputs)<1:
            raise Exception('setup data first') #can't happen
        self.keras_model=model(self.keras_inputs,
                               self.train_data.getNClassificationTargets(),
                               self.train_data.getNRegressionTargets(),
                               **modelargs)
    
    def saveCheckPoint(self,addstring=''):
        
        self.checkpointcounter=self.checkpointcounter+1 
        self.saveModel("KERAS_model_checkpoint_"+str(self.checkpointcounter)+"_"+addstring +".h5")    
           
        
    def loadModel(self,filename):
        #import h5py
        #f = h5py.File(filename, 'r+')
        #del f['optimizer_weights']
        from keras.models import load_model
        self.keras_model=load_model(filename, custom_objects=global_loss_list)
        self.optimizer=self.keras_model.optimizer
        self.compiled=True
        
    def compileModel(self,
                     learningrate,
                     **compileargs):
        if not self.keras_model:
            raise Exception('set model first') #can't happen
        #if self.compiled:
        #    return
        from keras.optimizers import Adam
        self.startlearningrate=learningrate
        self.optimizer = Adam(lr=self.startlearningrate)
        self.keras_model.compile(optimizer=self.optimizer,**compileargs)
        self.compiled=True
        
    def saveModel(self,outfile):
        self.keras_model.save(self.outputDir+outfile)
        import tensorflow as tf
        import keras.backend as K
        tfsession=K.get_session()
        saver = tf.train.Saver()
        tfoutpath=self.outputDir+outfile+'_tfsession/tf'
        import os
        os.system('rm -f '+tfoutpath)
        os.system('mkdir -p '+tfoutpath)
        saver.save(tfsession, tfoutpath)


        #import h5py
        #f = h5py.File(self.outputDir+outfile, 'r+')
        #del f['optimizer_weights']
        #f.close()
        
    def trainModel(self,
                   nepochs,
                   batchsize,
                   stop_patience=300, 
                   lr_factor=0.5,
                   lr_patience=2, 
                   lr_epsilon=0.003, 
                   lr_cooldown=6, 
                   lr_minimum=0.000001,
                   maxqsize=50, 
                   **trainargs):
        
        #make sure tokens don't expire
        from tokenTools import checkTokens, renew_token_process
        from thread import start_new_thread
        
        checkTokens()
        start_new_thread(renew_token_process,())
        
        self.train_data.setBatchSize(batchsize)
        self.val_data.setBatchSize(batchsize)
        
        averagesamplesperfile=self.train_data.getAvEntriesPerFile()
        samplespreread=maxqsize*batchsize
        nfilespre=max(int(samplespreread/averagesamplesperfile),2)
        print('best pre read: '+str(nfilespre)+'  a: '+str(averagesamplesperfile))
        
        #exit()
        
        self.train_data.maxFilesOpen=nfilespre
        self.val_data.maxFilesOpen=nfilespre
        
        self.keras_model.save(self.outputDir+'KERAS_check_last_model.h5')
        
        from DeepJet_callbacks import DeepJet_callbacks
        
        callbacks=DeepJet_callbacks(self.keras_model,
                                    stop_patience=stop_patience, 
                                    lr_factor=lr_factor,
                                    lr_patience=lr_patience, 
                                    lr_epsilon=lr_epsilon, 
                                    lr_cooldown=lr_cooldown, 
                                    lr_minimum=lr_minimum,
                                    outputDir=self.outputDir)
        nepochs=nepochs-self.trainedepoches
        
        self.keras_model.fit_generator(self.train_data.generator() ,
                            steps_per_epoch=self.train_data.getNBatchesPerEpoch(), 
                            epochs=nepochs,
                            callbacks=callbacks.callbacks,
                            validation_data=self.val_data.generator(),
                            validation_steps=self.val_data.getNBatchesPerEpoch(), #)#,
                            max_q_size=maxqsize,**trainargs)
        
        
        self.saveModel("KERAS_model.h5")
        
        import copy
        #reset all file reads etc
        tmpdc=copy.deepcopy(self.train_data)
        del self.train_data
        self.train_data=tmpdc
        
        return self.keras_model, callbacks.history
    
    
        

        
        
        
            
    
