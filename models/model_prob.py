"""
Implements the probabalistic model with a gaussian likelihood function
"""
# Import necessary libraries
import torch 
import torch.nn as nn

class model(nn.Module):
    def __init__(self, num_lstms, input_dim, output_dim=1, hidden_dim=64):
        super(model, self).__init__()
        self.lstm_out = hidden_dim
        self.num_lstms = num_lstms
        lstms = []

        lstms.append(nn.LSTMCell(input_dim, self.lstm_out))
        for i in range(1, self.num_lstms):
            lstms.append(nn.LSTMCell(self.lstm_out, self.lstm_out))

        self.lstms = nn.ModuleList(lstms)
        # mean and std deviation of the probability distribution of the next point for each time series. Number of
        # time series being predicted is given by output_dim
        self.mean = nn.Linear(self.lstm_out, output_dim)
        self.std = nn.Linear(self.lstm_out, output_dim)

    def forward(self, input, covariates, future = 0):
        """
        Implements the probabalistic model with a gaussian likelihood function
        """
        dev = input.device
        means = torch.Tensor().to(dev)
        stds = torch.Tensor().to(dev)
        outputs = []
        h_t = []
        c_t = []
        # add extra dimension to input and time_index so we can use torch.cat on them
        cond_ctx_len = input.size(1)
        pred_ctx_len = future

        # concatenate input and covariates
        if covariates.shape[2] != 0:
            input = torch.cat((input, covariates[:, 0:cond_ctx_len, :]), 2)

        for i in range(0, self.num_lstms):
            h_t.append(torch.zeros(input.size(0), self.lstm_out, dtype=torch.float).to(dev))
            c_t.append(torch.zeros(input.size(0), self.lstm_out, dtype=torch.float).to(dev))

        for i, input_t in enumerate(input.chunk(input.size(1), dim=1)):
            h_t[0], c_t[0] = self.lstms[0](input_t.squeeze(1), (h_t[0], c_t[0]))
            for n in range(1, self.num_lstms):
                h_t[n], c_t[n] = self.lstms[n](h_t[n - 1], (h_t[n], c_t[n]))
            mean = self.mean(h_t[n])
            std = self.std(h_t[n])
            means = torch.cat((means, mean.unsqueeze(1)), 1)
            stds = torch.cat((stds, std.unsqueeze(1)), 1)

        # Running softplus on the batch of outputs is a lot faster than running it in the loop
        stds = self.softplus(stds)
        # sample from the distribution
        # sample = self.sample(means[:, -1::], stds[:, -1::])
        # feed the mean for predicting the next target point instead of sampling from the distribution
        for i in range(future):  # if we should predict the future
            output_t = torch.cat((mean, covariates[:, cond_ctx_len + i, :]), 1)
            h_t[0], c_t[0] = self.lstms[0](output_t, (h_t[0], c_t[0]))
            for n in range(1, self.num_lstms):
                h_t[n], c_t[n] = self.lstms[n](h_t[n - 1], (h_t[n], c_t[n]))
            mean = self.mean(h_t[n])
            std = self.std(h_t[n])
            std = self.softplus(std) #enforce a positive standard deviation
            means = torch.cat((means, mean.unsqueeze(1)), 1)
            stds = torch.cat((stds, std.unsqueeze(1)), 1)
            # for prediction, we must run softplus on each output because we draw a sample from it
            # to pass to the next prediction step
            # sample = self.sample(mean, std)
        # Add extra dimension so means and stds can be concatenated into one tensor.
        means = means.unsqueeze(-1)
        stds = stds.unsqueeze(-1)
        outputs = torch.cat((means, stds), -1)
        return outputs

    def sample(self, mean, std):
        #mean, std = torch.split(output, 1, dim=1)
        normal_dist = torch.distributions.normal.Normal(mean, std)
        return normal_dist.sample()

    def softplus(self, x):
        """ Positivity constraint """
        softplus = torch.log(1+torch.exp(x))
        # Avoid infinities due to taking the exponent
        softplus = torch.where(softplus==float('inf'), x, softplus)
        return softplus

    def NLL(self, outputs, truth):
        """ Negative log likelihood"""
        mean, std = torch.split(outputs, 1, dim=3)
        mean = mean.squeeze(3)
        std = std.squeeze(3)
        diff = torch.sub(truth, mean)
        #loss =  torch.mean(torch.pow(diff, 2))
        #loss_verify = self.criterion(mean, truth)
        loss = torch.mean(torch.div(torch.pow(diff, 2), torch.pow(std, 2))) + 2*torch.mean(torch.log(std))
        return loss
        