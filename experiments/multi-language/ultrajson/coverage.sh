# first get python coverage
python_branch_cov=$(coverage report --show-missing | grep TOTAL | awk '{print $5}')
python_total_branch=$(coverage report --show-missing | grep TOTAL | awk '{print $4}')

# then get c coverage
c_cov_data=$(gcovr -r . -s | grep "[lb][a-z]*:")
c_line_per=$(echo "$c_cov_data" | grep lines | cut -d" " -f2 | rev | cut -c2- | rev)
c_line_abs=$(echo "$c_cov_data" | grep lines | cut -d" " -f3 | cut -c2-)
c_branch_per=$(echo "$c_cov_data" | grep branch | cut -d" " -f2 | rev | cut -c2- | rev)
c_branch_abs=$(echo "$c_cov_data" | grep branch | cut -d" " -f3 | cut -c2-)

total_branch_cov=$(echo "$python_branch_cov $c_branch_abs" | awk '{print $1 + $2}')


# echo "python_branch_cov: $python_branch_cov"
# echo "python_total_branch: $python_total_branch"
# echo "c_line_abs: $c_line_abs"
# echo "c_branch_abs: $c_branch_abs"
# echo "total_branch_cov: $total_branch_cov"

echo "$c_line_abs,$c_line_per,$c_branch_abs,$c_branch_per,0"
