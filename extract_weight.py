
## DEMO version for GPU fitting
###################################
## Created @ Apr. 12th, 2021
## By Yunshan Cheng and Dan Zhang
## contact: yunshancheng1@gmail.com
###################################
import numpy as np
import time
import math
#import matplotlib.pyplot as plt
import uproot
import emcee
import corner
import json

try:
    from pycuda.compiler import SourceModule
    import pycuda.driver as drv
    import pycuda.tools
    import pycuda.gpuarray
    import pycuda.autoinit
except ImportError:
    print(
        'Warning: Cuda libraries not found - RunManager.init() not available!'
     )

from gpu_modules.reweight import pandax4t_reweight_fitting 

start = drv.Event()
end = drv.Event()
GPUFunc     = SourceModule(pandax4t_reweight_fitting, no_extern_c=True).get_function("main_reweight_fitting")

GPUFuncRenormalization = SourceModule(pandax4t_reweight_fitting, no_extern_c=True).get_function("renormalization_reweight")

GPUlnLikelihood = SourceModule(pandax4t_reweight_fitting, no_extern_c=True).get_function("ln_likelihood")

file = open('./parameters/p4_run1_tritium_5kV.json')
config = json.load(file)

#parameters of interest
pde = np.float32(config['pde'])
g2b = np.float32(config['g2b'])
seg = np.float32(config['seg'])
nuissancePars = np.asarray([pde,g2b,seg],dtype = np.float32)

pde_g2b_theta = np.float32(config['python3.6']['nuissanceParRelativeUncertainty']['pde_g2b_theta'])
nuissanceParsReUnc = np.asarray([config['python3.6']['nuissanceParRelativeUncertainty']['pde'],
  config['python3.6']['nuissanceParRelativeUncertainty']['g2b'],
  config['python3.6']['nuissanceParRelativeUncertainty']['seg'] ] ,dtype = np.float32)

def get_ln_nuissance(nuissanceTheta):
  ln = np.double(0.);
  pde_i,g2b_i,seg_i = nuissanceTheta
  re_pde,re_g2b,re_seg = np.divide(nuissanceTheta,nuissancePars)
  #print(nuissanceParsReUnc,"test nuissance")
  #re_pde_rotate = (re_pde - 1.) * np.cos(pde_g2b_theta) + (re_g2b - 1.) * np.sin(pde_g2b_theta)
  #re_g2b_rotate = -(re_pde - 1.) * np.sin(pde_g2b_theta) + (re_g2b - 1.) * np.cos(pde_g2b_theta)
  #print(re_pde_rotate,re_g2b_rotate,re_seg,re_s2b_fraction,"test nuissance")
  re_pde_rotate = re_pde
  re_g2b_rotate = re_g2b
  ln += -0.5*np.power( (re_pde_rotate )/nuissanceParsReUnc[0],2)
  ln += -0.5*np.power( (re_g2b_rotate )/nuissanceParsReUnc[1],2)
  ln += -0.5*np.power( (re_seg - 1.0)/ nuissanceParsReUnc[2],2)
  return ln


#print("test lnproir ", get_ln_nuissance([0.094,0.77,19,0.25]))

fittingPars = np.asarray([0.1,0.02,1.5,20.],dtype = np.float32)#p0Recomb,p1Recomb,p0FlucRecombStretch

totalPars = np.append(nuissancePars,fittingPars,axis=0)
print('totalParameters ',totalPars)
print('nuissancePars', nuissancePars)
print('fittingPars',fittingPars)


#energy spectrum array initialize
#minE = np.float32(config['E_eeTh'])
minE = np.float32(0.)
maxE = np.float32(config['E_eeMaxSimu']) + 0.1
stepE = 0.25;
v_Erange = np.arange(minE,maxE,stepE)


#simulation data loading
oriTreeFile  = config['python3.6']['files']['oriSimuNpz']
oriTree = np.load(oriTreeFile)
simu_tree = oriTree['oriTree']
#branch_simu_newWeight = np.zeros((simu_tree.shape[0],1),dtype=np.float32)
#simu_tree = np.concatenate((simu_tree,branch_simu_newWeight),axis=1)
simu_tree_par = np.asarray([simu_tree.shape[0],simu_tree.strides[0]],dtype=np.float32)
simu_tree_bytes = simu_tree.size * simu_tree.dtype.itemsize
simu_tree_par     = np.asarray(np.append(simu_tree_par,[stepE,minE,maxE]),dtype=np.float32)
print('input simu_tree_par shape : ',simu_tree_par)

#boundary conditions
s1min = np.float32(config['s1min'])
s1u_c = np.float32(config['s1u_c'])
s2min = np.float32(config['s2min'])
s2minRaw = np.float32(config['s2minRaw'])
s2max = np.float32(config['s2max'])
s2u_c = np.float32(config['s2u_c'])
nHitsS1min = np.float32(config['nHitsS1min'])


#calibration data loading
def get_2dData():
  DATA_PATH = config['calDataRootFile']; 
  data_tree = uproot.open(DATA_PATH)["out_tree"]
  cS1_0= np.asarray(data_tree["qS1C_max"].array(),dtype=np.float32)
  cS2_0 = np.asarray(data_tree["qS2BC_max"].array(),dtype=np.float32)
  nPMTS1_max = np.asarray(data_tree["nPMTS1_max"].array(),dtype=np.float32) 
  cS1_0_raw = np.asarray(data_tree["qS1_max"].array(),dtype=np.float32)
  cS2_0_raw = np.asarray(data_tree["qS2_max"].array(),dtype=np.float32)
  Ndata_0 = cS1_0.shape[0]
  cS1 = np.array([],dtype=np.float32)
  cS2 = np.array([],dtype=np.float32)

  for i in range(Ndata_0):
    if (nPMTS1_max[i] > nHitsS1min) and (cS1_0[i] > s1min ) and (cS1_0[i] < s1u_c) and (cS2_0_raw[i] > s2minRaw) and (cS2_0_raw[i] < s2max) and (cS2_0[i] > s2min) and (cS2_0[i] < s2u_c ):
      cS1 = np.append(cS1,[cS1_0[i]])
      cS2 = np.append(cS2,[cS2_0[i]])
  return cS1,cS2

cS1,cS2 = get_2dData()
Ndata = np.asarray([cS1.shape[0]],dtype=np.int)
print("survived data: ",Ndata)



#for main_reweight_fitting
gpu_seed            = int(time.time()*100)
num_trials          = simu_tree.shape[0]
#num_trials          = 1000
GPUSeed             = np.asarray(gpu_seed, dtype=np.int32)
d_gpu_scale = {}
nThreads = 128
d_gpu_scale['block'] = (nThreads, 1, 1)
numBlocks = np.floor(float(num_trials) / float(nThreads))
d_gpu_scale['grid'] = (int(numBlocks), 1)


#binning setting
xbin = config['Bin_s1']
ybin = config['Bin_s2']
xmin=s1min
xmax=s1u_c
ymin=np.log10(s2min)
ymax=np.log10(s2u_c)
binning = np.asarray([xbin,xmin,xmax,ybin,ymin,ymax],dtype=np.double)

#for ln_likelihood
d_gpu_scale1 = {}
d_gpu_scale1['block'] = (nThreads, 1, 1)
d_gpu_scale1['grid'] = ( int(np.floor(float(Ndata[0])/float(nThreads) ) ),1)


def get_lnLikelihood(theta):

    #########################################
    ## Initialization
    ########################################
    global histogram2d_par
    histogram2d_par     = np.asarray(np.append([0.0],binning),dtype=np.double)
    global v_E
    v_E = v_Erange[:-1] + 0.5 * stepE
    v_E_dRdE = np.zeros(v_E.shape,dtype=np.float32)
    print('v_E shape: ',v_E_dRdE.shape[0])
    histogram2d_par     = np.append( histogram2d_par, v_E_dRdE)

    #print("dtype check ",histogram2d_par.dtype)
    #histogram2d_par = np.append(histogram2d_par, binning)
    global histogram2d;
    histogram2d = np.zeros((xbin,ybin),dtype = np.double)

    par_array = np.asarray(theta, dtype=np.float32)

    # important step, need to push (or copy) it to GPU memory so that GPU function can use it
    # this step take time so shall minimize the number of times calling it
    start.record()
    #simu_tree_gpu = drv.mem_alloc(simu_tree_bytes)
    #drv.memcpy_htod(simu_tree_gpu,simu_tree)
    global out_weight
    out_weight = np.zeros(simu_tree.shape[0],dtype = np.float32)
    global out_normalization
    out_normalization = np.zeros(simu_tree.shape[0],dtype = np.float32)
    mode = np.uint(1)
    tArgs               = [
        drv.In(par_array),
        drv.In(simu_tree), drv.In(simu_tree_par),
        drv.InOut(histogram2d), drv.InOut(histogram2d_par),
        drv.InOut(out_weight),drv.InOut(out_normalization),
        mode
    ]

    # Run the GPU code
    GPUFunc(*tArgs, **d_gpu_scale)
    #end.record()
    drv.Context.synchronize()
    v_E_dRdE = histogram2d_par[7:]
    v_E_dRdE = np.asarray(np.append([v_E_dRdE.shape[0]],v_E_dRdE), dtype = np.float32)
    v_E = np.asarray(np.append([v_E.shape[0]],v_E),dtype = np.float32)
    print('v_E_dRdE ',v_E_dRdE)
    print('v_E ',v_E)

    histogram2d = histogram2d * 0.;
    histogram2d_par = histogram2d_par[:7]
    histogram2d_par[0] = 0.
    print('check dtype ', simu_tree.dtype,histogram2d_par.dtype)
    tArgsR = [ 
      drv.In(v_E),drv.In(v_E_dRdE),
      drv.In(simu_tree), drv.In(simu_tree_par),
      drv.InOut(out_weight),drv.In(out_normalization),
      drv.InOut(histogram2d), drv.InOut(histogram2d_par),
    ]
    GPUFuncRenormalization(*tArgsR , **d_gpu_scale)
    drv.Context.synchronize()
    return histogram2d_par[0] 
    

def get_lnprob(theta):
    NoNui=nuissancePars.shape[0]
    nuissancePar_i = theta[:NoNui]
    lp = get_ln_nuissance(nuissancePar_i)
    if not np.isfinite(lp):
        return -np.inf
    lnprob =  get_lnLikelihood(theta)
    return lp + lnprob

def get_newWeight(theta,filename):
    likelihood = get_lnLikelihood(theta)
    print("sum2: ",histogram2d_par[0])
    x0 = np.linspace(xmin,xmax,num=np.int(xbin))
    y0 = np.linspace(ymin,ymax,num=np.int(ybin))
    xv, yv = np.meshgrid(x0,y0)
    #c =plt.pcolor(xv,yv,histogram2d,cmap='magma',vmin=0, vmax = histogram2d.max())
    #plt.axis([xmin,xmax,ymin,ymax])
    #plt.colorbar(c)
    print("likelihood_output: ",likelihood)
    #plt.show()
    np.savez(filename,histogram2d=histogram2d,qmc_tree=simu_tree,pars=theta,v_E=v_E,v_E_dRdE = histogram2d_par[7:],new_weight=out_weight,normalization = out_normalization)
    #plt.savefig('bestFitting.png')


outFile = config['python3.6']['files']['bestNpz']
get_newWeight([0.1,4,21.32,0,0,0,1.,27.222],outFile)