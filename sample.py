# Add JTNN and 3N-MCTS lib to PYTHONPATH
import os, sys
sys.path.append(os.path.join(os.getcwd(), 'jtnn'))
sys.path.append(os.path.join(os.getcwd(), 'mcts'))

import json
import molvs
import torch
import rdkit
from glob import glob
from tqdm import tqdm
from jtnn import Vocab, JTNNVAE
from atc import ATCModel, code_lookup
from mcts.plan import generate_plan

# How many compounds to generate for each class
N_SAMPLES = 100

# Silence rdkit
lg = rdkit.RDLogger.logger()
lg.setLevel(rdkit.RDLogger.CRITICAL)


def load_jtnn():
    # Load configs & data
    model_path = 'data/jtnn/model'
    conf = json.load(open('data/jtnn/config.json', 'r'))

    vocab = [t.strip() for t in open('data/jtnn/vocab.dat')]
    vocab = Vocab(vocab)

    labels = [l.strip() for l in open('data/jtnn/labels.dat')]
    n_classes = len(labels)

    # Load JTNN VAE model
    hidden_size = conf['hidden_size']
    latent_size = conf['latent_size']
    depth = conf['depth']
    model = JTNNVAE(vocab, hidden_size, latent_size, depth, n_classes)
    saves = sorted(os.listdir(model_path))
    path = os.path.join(model_path, saves[-1])
    model.load_state_dict(torch.load(path))
    model = model.cuda()
    return model, labels


if __name__ == '__main__':
    # Load existing PubChem compounds to check against
    pubchem = set()
    for fn in tqdm(glob('data/smiles/*.smi')):
        with open(fn, 'r') as f:
            for line in f:
                pubchem.add(line.strip())

    # Load ATC prediction model
    atc_model = ATCModel.load('data/atc')
    atc_lookup = code_lookup()

    # Load JTNN model
    model, labels = load_jtnn()

    # Generate compounds
    samples = {}
    torch.manual_seed(0)
    for i, label in enumerate(labels):
        smis = []
        for _ in range(N_SAMPLES):
            smi = model.sample_prior(prob_decode=True, class_=i)
            smis.append(smi)
        samples[label] = smis

    # Validate and standardize generated compounds
    for label, smis in samples.items():
        ok = []
        for smi in smis:

            # Validate SMILES
            errs = molvs.validate_smiles(smi)
            if errs:
                print('Validation error(s):', errs)
                continue

            # Standardize SMILES
            smi = molvs.standardize_smiles(smi)

            # Check if exists already
            if smi in pubchem:
                print('Exists in PubChem')
                continue

            # Try to generate a synthesis plan
            synth_plan = generate_plan(smi)
            if synth_plan is None:
                continue

            ok.append(smi)
        atc_codes = [atc_lookup[i] for i in atc_model.predict(ok)]
        samples[label] = list(zip(ok, atc_codes))

    # Save generated compounds
    with open('data/jtnn/compounds.json', 'w') as f:
        json.dump(samples, f)