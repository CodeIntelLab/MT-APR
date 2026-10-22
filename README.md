# MT-APR

This repository contains the source code and experimental artifacts for **MT-APR**, a multi-template-guided automated program repair approach.

## Overview

MT-APR leverages multiple repair templates to provide guidance for LLM-based patch generation. The project is designed to investigate the effectiveness of multi-template guidance for automated program repair.

## Project Structure

```text
MT-APR/
├── generator/       # Patch generation
├── prompt/          # Prompt templates
├── result/          # Experimental results
├── RWB/             # RWB-related experiments
├── TBar/            # TBar templates and related resources
├── template/        # Repair templates
├── test_data/       # Test data
├── utils/           # Utility functions
└── validator/       # Patch validation and testing
```

## Requirements

The experiments are primarily conducted with Python and Defects4J. Please refer to the source code and configuration files for the required dependencies and environment settings.

## Dataset

MT-APR is evaluated on benchmark datasets for automated program repair, including **Defects4J** and **RWB**.

The benchmark datasets are not included in this repository and should be obtained from their respective official sources.

## Usage

Please refer to the scripts and configuration files in this repository for running patch generation and validation experiments.

## Paper

This repository accompanies the research paper on MT-APR.

## License

The code is provided for research purposes.
