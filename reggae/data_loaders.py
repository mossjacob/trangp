import csv
import pandas as pd
import numpy as np
from sklearn import preprocessing

class DataHolder(object):
    def __init__(self, data, noise, time):
        self.m_obs, self.f_obs = data
        if noise is not None:
            self.σ2_m_pre, self.σ2_f_pre = noise
        self.t = time[0]
        self.τ = time[1]
        self.common_indices = time[2]

def load_3day_dros():
    with open('data/3day/GSE47999_Normalized_Counts.txt', 'r', 1) as f:
        contents = f.buffer
        df = pd.read_table(contents, sep='\t', index_col=0)
    replicates = 3
    columns = df.columns[df.columns.str.startswith('20,000')][::replicates]
    known_target_genes = ['FBgn0011774', 'FBgn0030189', 'FBgn0031713', 'FBgn0032393', 'FBgn0037020', 'FBgn0051864']
    tf_names = ['FBgn0039044']
    genes_df = df[df.index.isin(known_target_genes)][columns]
    tfs_df = df[df.index.isin(tf_names)][columns]

    #Normalise across time points
    normalised = preprocessing.normalize(np.r_[genes_df.values,tfs_df.values])
    genes = normalised[:-1]
    tfs = np.atleast_2d(normalised[-1])
    return (genes_df, np.float64(genes)), (tfs_df, np.float64(tfs)), np.array([2, 10, 20])


def load_barenco_puma():
    mmgmos_processed = True
    if mmgmos_processed:
        with open('data/barencoPUMA_exprs.csv', 'r') as f:
            df = pd.read_csv(f, index_col=0)
        with open('data/barencoPUMA_se.csv', 'r') as f:
            dfe = pd.read_csv(f, index_col=0)
        columns = [f'cARP{r}-{t}hrs.CEL' for r in range(1, 4) for t in np.arange(7)*2]
    else:
        with open('data/barenco_processed.tsv', 'r') as f:
            df = pd.read_csv(f, delimiter='\t', index_col=0)

        columns = [f'H_ARP1-{t}h.3' for t in np.arange(7)*2]

    known_target_genes = ['203409_at', '202284_s_at', '218346_s_at', '205780_at', '209295_at', '211300_s_at']
    genes = df[df.index.isin(known_target_genes)][columns]
    genes_se = dfe[dfe.index.isin(known_target_genes)][columns]

    assert df[df.duplicated()].size == 0

    index = {
        '203409_at': 'DDB2',
        '202284_s_at': 'p21',
        '218346_s_at': 'SESN1',
        '205780_at': 'BIK',
        '209295_at': 'TNFRSF10b',
        '211300_s_at': 'p53'
    }
    genes.rename(index=index, inplace=True)
    genes_se.rename(index=index, inplace=True)

    # Reorder genes
    genes_df = genes.reindex(['DDB2', 'BIK', 'TNFRSF10b', 'p21', 'SESN1', 'p53'])
    genes_se = genes_se.reindex(['DDB2', 'BIK', 'TNFRSF10b', 'p21', 'SESN1', 'p53'])

    tfs_df = genes_df.iloc[-1:]
    genes_df = genes_df.iloc[:-1]
    genes = genes_df.values
    tfs = tfs_df.values

    tf_var = genes_se.iloc[-1:].values**2
    gene_var = genes_se.iloc[:-1].values
    gene_var = gene_var*gene_var

    tfs_full = np.exp(tfs + tf_var/2)
    genes_full = np.exp(genes+gene_var/2)

    tf_var_full = (np.exp(tf_var)-1)*np.exp(2*tfs + tf_var)
    gene_var_full = (np.exp(gene_var)-1)*np.exp(2*genes + gene_var) # This mistake is in Lawrence et al.

    tf_scale = np.sqrt(np.var(tfs_full[:, :7], ddof=1))
    tf_scale = np.c_[[tf_scale for _ in range(7*3)]].T
    tfs = np.float64(tfs_full / tf_scale).reshape(3, 7)
    tf_var = (tf_var_full / tf_scale**2).reshape(3, 7)

    gene_scale = np.sqrt(np.var(genes_full[:,:7], axis=1, ddof=1))
    gene_scale = np.c_[[gene_scale for _ in range(7*3)]].T
    genes = np.float64(genes_full / gene_scale).reshape(5, 3, 7).swapaxes(0, 1)
    gene_var = np.float64(gene_var_full / gene_scale**2).reshape(5, 3, 7).swapaxes(0, 1)

    return (genes_df, genes), (tfs_df, np.float64(tfs)), gene_var, tf_var, np.arange(7)*2           # Observation times