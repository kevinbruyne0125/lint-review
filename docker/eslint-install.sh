#!/bin/bash

# Check for /src/package.json if it doesn't exist exit.
if [ ! -e /src/package.json  ]; then
	exit 0
fi

cd /tool || exit 1

# Use grep & awk to find eslint packages.
while read -r package
do
	# Clean up the JSON into something we can put into npm install.
	package_name=$(echo "$package" | sed -e 's/,//' | sed -e 's/"//g' | sed -e 's/://' | awk '{print $1 "@" $2}')

	# Install required plugins into /tool/node_modules
	npm install "$package_name"
done <  <(grep -i -E 'eslint-[plugin|config]-*' /src/package.json)
