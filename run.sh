#!/bin/bash

apt update -y
apt install -y zmap

chmod 777 zmap


zmap -p 3128-w global.txt | ./zmap -p 3128

