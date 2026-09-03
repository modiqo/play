#!/bin/sh
git -C "$1" rev-list --count HEAD
